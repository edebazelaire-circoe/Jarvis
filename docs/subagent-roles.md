# Rôles de sous-agent, missions et Mission Owner

Page canonique des rôles de sous-agent, des marqueurs que le cerveau écrit pour les déclarer, des missions
et des instances d'agent. Elle décrit le contrat ; le câblage d'exécution (lancement, persistance,
affichage) est signalé là où il manque encore.

| Contrat | Code | Tests |
| --- | --- | --- |
| Registre des rôles, résolution des marqueurs, ce que le hook appose | `jarvis/domain/subagent_roles.py` | `tests/unit/test_subagent_roles.py` |
| Hook `PreToolUse` (méthode, loadout, journal `agent.role_applied`) | `jarvis/runtime/routing_hook.py` | `tests/unit/test_subagent_roles.py`, `tests/unit/test_routing_hook.py` |
| Lecture du registre pour Settings (`GET /api/subagent-roles`) | `jarvis/runtime/control_center.py` (`_subagent_roles_payload`) | `tests/unit/test_subagent_roles.py` |
| Onglet Réglages > Sous-agents (section 8) | `jarvis/runtime/control_center_subagents_settings.js` | `tests/unit/test_control_center_subagents_settings_js.py` |
| Grammaire des marqueurs de tête, déclaration | `jarvis/domain/agent_markers.py` | `tests/unit/test_agent_markers.py` |
| Missions, instances, Mission Owner, éphémère | `jarvis/domain/missions.py` | `tests/unit/test_missions.py` |
| Work Methods | `jarvis/domain/work_methods.py`, voir [work-methods.md](work-methods.md) | `tests/unit/test_work_methods.py` |
| Relations typées, tableaux de relation, relais | `jarvis/domain/agent_relations.py`, voir [agent-relations.md](agent-relations.md) | `tests/unit/test_agent_relations.py` |

Les décisions produit dont ces contrats découlent (D01 à D25) sont celles du handoff
`tasks/jarvis-organic-agent-orchestration/docs/01-decisions.md`.

## 1. Le registre des rôles

Un rôle est l'identité fonctionnelle d'une instance d'agent. Le registre `subagent_roles.ROLES` est la
seule source : identifiant, marqueur, libellé français, mission, instructions (méthode apposée par le hook),
outils, profil par défaut, identité visuelle, capacités, Work Methods permises, rôle de loadout.

| id = marqueur | Libellé | Nom dans le handoff | Profil | Mission Owner | Lance des agents | Loadout | Work Methods (défaut en gras) | Visuel (icône, accent, badge) | Proposé au cerveau | Proposé aux agents |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `interviewer` | Intervieweur | Interviewer | general | non | non | profil | — | question, violet, INT | oui | **non** |
| `research` | Recherche documentaire | Document Research | general | non | non | `research` | quick, deep, comparative | book, teal, DOC | oui | oui |
| `web-research` | Recherche web | Web Research | general | non | non | profil | quick, deep, comparative | globe, sky, WEB | oui | oui |
| `coder` | Développement | Developer | code | oui | oui | `coder` | bug-investigation | code, amber, DEV | oui | oui |
| `concept` | Conceptualisation | Conceptualizer | general | non | non | profil | — | lightbulb, rose, CPT | oui | oui |
| `research-lead` | Direction de recherche | Research Lead | general | oui | oui | `research` | **deep**, comparative, quick | compass, indigo, DIR | oui (Slice 07) | oui |
| `qa` | Contrôle qualité | QA / Quality Analyst | general | non | non | `reviewer` | **result-review**, bug-investigation | shield-check, lime, QA | oui (Slice 07) | oui |

Tous les rôles sont actifs (`enabled=True`). Les ids des méthodes sont abrégés : `quick-research`,
`deep-research`, `comparative-research` ([work-methods.md](work-methods.md)).

Règles :

- **Les ids ne changent pas.** Les cinq premiers indexent les surcharges d'instructions déjà enregistrées par
  l'utilisateur (prompt `subagent_role.<id>`, Settings > Sous-agents) ; les renommer les rendrait orphelines.
  Un nouveau rôle reçoit un nouvel id, additif.
- **Les ids sont des données explicites**, jamais déduits d'un libellé : « Développeur : corriger le bug »
  ne déclare aucun rôle.
- **Actif, proposé, désactivé.** Trois drapeaux distincts :
  - `enabled` : le rôle existe pour le hook. Son marqueur est annoncé (`agent_markers.ANNOUNCED_ROLES`),
    consommé du libellé, et le hook appose sa méthode et son loadout. Désactivé, un rôle se lit comme un mot
    inconnu (marqueur gardé dans le libellé, repli sur la consigne) et seul `resolve_role` direct rend
    `disabled` ;
  - `offered_to_brain` : le rôle figure dans la section « TYPE DE DEMANDE » du cerveau (`brain_rules`).
    Tous les rôles le sont depuis la Slice 07 (`research-lead` et `qa` ne l'étaient pas avant, section 9) ; le
    baisser retire le rôle de la règle et rien d'autre, et Settings le dit (« pas encore proposé au cerveau ») ;
  - `offered_to_subagents` : le rôle figure dans les capacités apposées sur la consigne d'un agent qui peut
    lancer des agents (section 1bis). Faux pour l'Intervieweur, qui ne parle à l'utilisateur que par le
    cerveau.
- `constrained_output` : la réponse finale du rôle a une forme imposée par ses instructions (l'Intervieweur :
  une seule ligne `QUESTION :` / `PRÊT :`, « pas d'autre texte »). Le texte généré pour ce rôle ne lui demande
  alors jamais d'ajouter quoi que ce soit au compte rendu ; il renvoie au dossier de mission. Donnée explicite,
  jamais déduite des instructions, et un test l'impose à tous les rôles.
- **Pourquoi activer `research-lead` et `qa` dès la Slice 04.** Leur câblage registre/hook est complet ici
  (méthode, capacités, Work Method, loadout) et ne touche pas le prompt du cerveau. Effets immédiats : un
  agent qui lance des agents (Développement, Direction de recherche) peut demander `[general] [qa]` ou
  `[general] [research-lead]` et obtient la bonne méthode ; l'alias historique `[code] [reviewer]` reçoit la
  méthode du Contrôle qualité. Depuis la Slice 07, `PROFILE_RULE` enseigne `[qa]` et plus `[reviewer]`.
- Mission Owner **n'est pas un rôle** (section 5). Il n'existe ni rôle « Orchestrateur » ni rôle
  « Owner ».

### Alias de compatibilité

`subagent_roles.ROLE_ALIASES` relie un marqueur historique à l'id qu'il désigne :

| Alias | Rôle | Pourquoi |
| --- | --- | --- |
| `reviewer` | `qa` | rôle de loadout historique de la relecture (`memory_settings.LOADOUT_ROLES`) |

`coder` et `research` n'ont pas besoin d'alias : ce sont à la fois des rôles du registre et des rôles de
loadout. Un alias n'est pas un rôle (`role_by_id("reviewer")` est `None`), mais il résout son rôle :
`role_for("reviewer")` rend `qa`, et `[code] [reviewer]` reçoit la méthode du Contrôle qualité (Slice 04).
Le hook continue de lire `[code] [reviewer]` comme la clé de loadout `code:reviewer`, comme avant. Condition de retrait de l'alias :
[legacy/subagent-role-aliases.md](legacy/subagent-role-aliases.md).

### Résolution d'un marqueur

`resolve_role(marker) -> RoleResolution(role_id, marker, status)` est déterministe et ne lève jamais :

| Marqueur | `role_id` | `status` |
| --- | --- | --- |
| absent ou vide | `undeclared` | `undeclared` |
| marqueur d'un rôle actif (`coder`, casse ignorée) | son id | `declared` |
| marqueur d'un rôle désactivé (aucun aujourd'hui) | son id | `disabled` |
| alias (`reviewer`) | l'id visé (`qa`) | `alias` |
| tout autre mot (`zorg`) | `unknown` | `unknown`, marqueur gardé (24 caractères) |

`undeclared` et `unknown` sont des ids réservés (`RESERVED_ROLE_IDS`) qu'aucun rôle ne peut prendre. Une
instance sans rôle déclaré s'affiche comme générale et n'arrête pas le travail.

Limite actuelle : la grammaire de tête (section 2) ne remonte comme rôle que les mots de
`ANNOUNCED_ROLES` ; un mot inconnu (`[code] [zorg] …`) n'est pas un rôle, reste dans le libellé et donne
`undeclared`. Le statut `unknown` n'est donc atteint aujourd'hui que par un appel direct à `resolve_role` ou
par un id persisté que le registre ne connaît plus (`AgentInstance.role_known`). Faire remonter un marqueur
inconnu jusqu'à Core pour qu'il se dégrade visiblement est une décision des Slices 03 (contrat transmis) et
05 (câblage).

### Identité visuelle

`RoleVisual(icon, accent, badge)` est une donnée du registre, en jetons :

- `icon` : nom d'icône (`[a-z][a-z0-9-]{1,31}`), que le frontend traduit en pictogramme ;
- `accent` : un jeton de `ROLE_ACCENTS` (`violet`, `teal`, `sky`, `amber`, `rose`, `indigo`, `lime`,
  `slate`, `orange`, `cyan`), que le frontend traduit en variable CSS. Aucune couleur n'est écrite ici ;
- `badge` : 2 à 4 capitales ou chiffres, redondant avec l'icône et l'accent : l'identité ne repose jamais
  sur la couleur seule.

Chaque rôle a sa propre icône, son propre accent et son propre badge (vérifié au chargement du module).
Le frontend lit ces jetons, il ne les recopie pas dans des conditions.

### Capacités

- `can_own_mission` : l'instance peut porter la responsabilité d'une mission (section 5). Exige `can_spawn`.
- `can_spawn` : l'instance peut lancer d'autres agents. Elle doit lister l'outil `Agent` (`SPAWN_TOOL`) dans
  `tools`, et réciproquement. **Mécanique depuis la Slice 05** : un rôle `can_spawn=False` part sous le type
  d'agent restreint `jarvis-no-spawn` (sans `Agent`/`Task`), imposé par le hook, et un appel `Agent` émis
  depuis ce type est refusé ; sa charte ne l'invite plus à déléguer
  ([agent-orchestration.md](agent-orchestration.md) §3).
- `work_methods` / `default_work_method` : ids de [Work Methods](work-methods.md) livrées
  (`work_methods.BUILTIN_METHODS`) permises et celle proposée par défaut. Vérifié au chargement du module :
  un rôle ne cite qu'une méthode livrée qui s'applique à lui (`check_role_methods`), et une méthode ne vise
  que des rôles du registre. La méthode par défaut est apposée sur la consigne, sauf si l'appelant en
  choisit une autre permise au rôle par un marqueur de tête (`[general] [research] [quick-research] …`,
  section 2) ; une méthode non permise retombe sur le défaut (`method_not_allowed`, consigné). Les rôles existants
  n'ont pas de méthode par défaut : leurs instructions sont déjà leur méthode.
- `loadout_role` : rôle de loadout (`LOADOUT_ROLES`) dont l'instance prend les savoirs, ou rien (le loadout
  du profil). Le hook l'applique (`agent_markers.read_loadout_role`) : un marqueur qui est déjà un rôle de
  loadout (`coder`, `reviewer`, `research`) est pris tel quel, sinon le `loadout_role` du rôle actif
  (`qa` -> `reviewer`, `research-lead` -> `research`). `LOADOUT_ROLES` n'est pas étendu : aucun rôle n'a
  besoin d'un loadout à lui, et les règles `memory.loadouts` enregistrées restent valides.
- `tools` : les outils que le rôle utilise, affichés. Aucun consommateur ne s'en sert pour restreindre les
  outils du CLI (section 1bis).

Tous ces champs paraissent dans `SubagentRole.as_dict()`, donc dans `GET /api/subagent-roles` (section 1ter).

### 1bis. Ce que le hook appose pour un rôle

Le hook `PreToolUse` lit le marqueur de rôle (`read_role`), le résout (`role_for` : marqueur d'un rôle actif
ou alias) et appose, après la charte et le playbook éventuel, une seule fois (marque `ROLE_MARK`), le texte
de `subagent_roles.role_brief(role, overrides)` :

1. `MÉTHODE DU RÔLE JARVIS (<libellé>)` suivi des **instructions** : la surcharge de l'utilisateur
   (`subagent_role.<id>`, lue dans l'instantané `runtime/subagent-roles.json`) si elle est non vide, sinon le
   défaut du code ;
2. `CAPACITÉS DU RÔLE` (`capabilities_text`), généré du registre : pour un rôle `can_spawn`, il peut lancer
   des agents (outil `Agent`), avec la liste des marqueurs `[profil] [rôle]` des rôles actifs
   `offered_to_subagents` ; sinon « Vous ne lancez aucun autre agent », avec la mention que cette règle
   **prime sur l'invitation à déléguer de la charte du chantier** (`AGENT_TASK_CHARTER`, apposée avant : ordre
   réel charte, consigne, playbook, rôle), et où signaler un autre travail utile : le compte rendu, ou le
   dossier de mission pour un rôle `constrained_output`. La charte elle-même ne connaît pas les rôles ; la
   rendre consciente des rôles relève de la Slice 05 ;
3. la **Work Method par défaut** du rôle (`work_methods.render_method`), s'il en a une : principes, critères
   de qualité, relations à envisager, avec sa clé exacte `<id>@<version>` et la mention « des réflexes, pas
   des étapes ».

Seules les instructions sont éditables, par la voie existante `POST /api/prompts/subagent_role.<id>`
(révisions optimistes) ; capacités et méthode suivent toujours le code. Aucune autre voie d'écriture.

**`can_spawn` et l'outillage effectif.** Le CLI donne l'outil `Agent` à tout sous-agent `general-purpose` :
`can_spawn` ne retire aucun outil aujourd'hui. Il est effectif par la consigne (bloc 2), et il reste lié à
`tools` (`Agent` présent si et seulement si `can_spawn`). Le refus mécanique — un type d'agent personnalisé
à liste d'outils réduite, sans `Agent` pour un rôle qui ne lance pas (`--agents` du CLI et réécriture de
`subagent_type` par le hook) — n'est pas câblé : il n'est pas prouvé sur le CLI installé (la sonde de la
Slice 04 n'a pas pu tourner) et relève de la Slice 05, en bac à sable. Le hook ne peut pas non plus refuser
un appel imbriqué selon le rôle de l'appelant : l'événement porte l'`agent_id` de l'appelant, pas son rôle.

**Journal `agent.role_applied`** (codes, jamais le texte) : `role` (marqueur tel qu'écrit), `role_id` et
`role_status` (`declared`, ou `alias` pour `[reviewer]`), `profile`, `source` (`override` ou `default`, selon
l'id canonique), `work_method` (`<id>@<version>` ou `null`), `loadout_role`, `can_spawn`,
`caller_agent_id` (l'`agent_id` du sous-agent appelant pour un appel imbriqué, `null` pour le cerveau : de quoi
vérifier après coup qu'un rôle `can_spawn=False` n'a lancé personne), `instructions_chars` (tout le texte
apposé à partir de `ROLE_MARK` : instructions, capacités et méthode), `role_instructions_chars` (les seules
instructions effectives, surcharge ou défaut), `tool_use_id`.

Un marqueur inconnu (`[code] [zorg] …`) n'est pas un rôle : rien n'est apposé, le libellé le garde.

### 1ter. Lecture pour Settings : `GET /api/subagent-roles`

Route de lecture seule du Control Center (`_subagent_roles_payload`), **`schema_version` 2** depuis la
Slice 04 :

| Clé | Contenu |
| --- | --- |
| `roles[]` | `SubagentRole.as_dict()` (dont `enabled`, `offered_to_brain`, `offered_to_subagents`, `constrained_output`, `aliases`, `visual`, capacités, `work_methods`, `default_work_method`, `loadout_role`), plus `instructions` effectives, `default_instructions`, `modified`, `default_revision`, `revision`, `conflict` |
| `work_methods[]` | `WorkMethod.to_payload()` de chaque méthode livrée |
| `aliases` | `ROLE_ALIASES` (`{"reviewer": "qa"}`) |
| `accents` | `ROLE_ACCENTS`, les jetons que le frontend traduit en variables CSS |
| `relation_labels` | `work_methods.RELATION_LABELS` : libellé français de chaque relation citée par `useful_relations` (Slice 10) |
| `instructions_max_chars` | `prompt_registry.MAX_OVERRIDE_TEXT` (8 192) : borne d'une surcharge d'instructions, affichée près du compteur (Slice 10) |
| `reserved_role_ids` | `undeclared`, `unknown` : à afficher comme rôle général ou inconnu, jamais deviné |
| `execution_gate`, `mission_path`, `application` | inchangés depuis la version 1 |

Version 2 n'ajoute que des clés (`relation_labels` et `instructions_max_chars` ajoutées par la Slice 10, même règle) : un lecteur de la version 1 lit la même chose. Une valeur existante change
depuis la Slice 01 : `coder.tools` contient `Agent`.

## 2. Les marqueurs de tête d'un appel `Agent`

L'outil `Agent` appartient au CLI : le cerveau ne peut pas lui ajouter de paramètre. Il déclare ce que
JARVIS doit savoir d'un sous-agent par des marqueurs entre crochets en tête de la `description`. Une seule
grammaire, `agent_markers.parse_head`, lue à l'identique par le hook `PreToolUse`
(`jarvis/runtime/routing_hook.py`) et par le suivi des tâches (`jarvis/runtime/agent_tasks.py`).

- La **tête** est la suite des groupes entre crochets au début du texte, au plus cinq : quatre mots et le
  marqueur éphémère.
- Un **mot** est un groupe ASCII `[mot]` de 2 à 24 lettres, `_` ou `-`, blancs internes tolérés.
- Le **premier mot** est toujours consommé. S'il nomme un rôle annoncé, c'est le rôle et le profil reste
  `general`. S'il nomme un profil (`code`, `desktop`, `fast`, `general`), le **second mot** est consommé
  s'il nomme un rôle annoncé (ou un rôle de production de présentation), sinon il reste dans le libellé.
  Les rôles annoncés sont `agent_markers.ANNOUNCED_ROLES` : rôles de loadout, marqueurs des rôles **actifs**
  du registre et alias.
- Le **marqueur éphémère** `[éphémère]` est un jeton exact (minuscules, accents, sans blanc interne), suivi
  d'au moins un espace ou une tabulation, une seule fois, à n'importe quelle place de la tête. Il est
  transparent : retiré, les mots restants se lisent comme s'il n'avait jamais été là. Il ne compte que si un
  **libellé non vide reste après tous les marqueurs de tête** (`[éphémère] [code]`, `[ CODE ] [éphémère] `
  ne déclarent rien : une tâche qu'on ne sait pas nommer ne se tait pas).
- **Échec sûr** : casse ou accents différents (`[Éphémère]`, `[ephemere]`), marqueur collé au texte, marqueur
  en double (deux dans la tête, ou un second juste après, même collé ou en fin de texte), marqueur au milieu
  du libellé, aucun libellé après la tête : rien n'est déclaré, le texte reste intact, la tâche est
  ordinaire, visible et annoncée.
- **Modificateurs d'orchestration** (Slice 05) : seulement après un rôle consommé, les mots suivants sont
  consommés tant qu'ils sont `[mission]` (l'agent ouvre et possède une sous-mission de la mission de son
  appelant), `[relais]` (Slice 06 : l'agent reprend la mission de son appelant par le relais que celui-ci a
  préparé, [agent-relations.md](agent-relations.md) §10.4) ou l'id d'une Work Method livrée (méthode choisie),
  chacun une fois, dans n'importe quel ordre.
  Sans rôle, ils restent dans le libellé, comme avant. Leur validité est jugée par le hook
  ([agent-orchestration.md](agent-orchestration.md) §3) ; le rôle de production de présentation ne se cherche
  que parmi les trois premiers mots, comme avant.
- Le drapeau éphémère ne se lit que sur la `description`. Le repli historique du hook sur la clé `prompt`
  ne vaut que pour le profil et le rôle.

| Description | Profil | Rôle | Éphémère | Libellé |
| --- | --- | --- | --- | --- |
| `[code] [coder] Corriger la coquille` | code | coder | non | Corriger la coquille |
| `[éphémère] [code] [coder] Corriger la coquille` | code | coder | oui | Corriger la coquille |
| `[code] [éphémère] [coder] Corriger la coquille` | code | coder | oui | Corriger la coquille |
| `[code] [coder] [éphémère] Corriger la coquille` | code | coder | oui | Corriger la coquille |
| `[éphémère] Liste des tâches` | general | aucun | oui | Liste des tâches |
| `[reviewer] Relire` | general | reviewer (-> `qa`) | non | Relire |
| `[code] [inconnu] Relire` | code | aucun | non | [inconnu] Relire |
| `[code] [coder] [Éphémère] Corriger` | code | coder | non | [Éphémère] Corriger |
| `[éphémère] [code]` | code | aucun | non | (vide) |
| `[code] [qa] Relire` | code | qa | non | Relire |
| `[code] [zorg] Relire` | code | aucun (repli sur la consigne) | non | [zorg] Relire |
| `[general] [research-lead] [mission] Comparer` | general | research-lead, `[mission]` | non | Comparer |
| `[general] [research] [quick-research] Chercher` | general | research, méthode `quick-research` | non | Chercher |
| `[general] [mission] Comparer` | general | aucun | non | [mission] Comparer |
| `[code] [coder] [relais] Suite du correctif` | code | coder, `[relais]` | non | Suite du correctif |

Avant cette grammaire commune (I-005), le suivi exigeait `[éphémère]` en premier tandis que le hook ne
lisait que des mots ASCII en tête : `[éphémère] [code] [coder] …` perdait profil et rôle côté hook,
`[code] [coder] [éphémère] …` perdait le drapeau côté suivi. Les descriptions déjà écrites
(`[éphémère] Libellé`, `[profil] [rôle] Libellé`) se lisent comme avant ; sans le jeton `[éphémère]`, tous
les lecteurs rendent exactement l'ancien résultat. Les seuls écarts, voulus, touchent ce jeton : il est lu à
travers (profil, rôle, loadout, rôle de production et libellé, dans la description comme dans la consigne),
il est accepté ailleurs qu'en premier, et deux formes autrefois déclarées éphémères ne le sont plus, du côté
sûr : un second marqueur plus loin dans la tête (`[éphémère] [code] [éphémère] x`, autrefois éphémère de
description `[code] [éphémère] x`) et une tête sans libellé (`[éphémère] [code]`). Ces écarts sont figés par
`tests/unit/test_agent_markers_equivalence.py`, qui garde une copie de l'ancien comportement comme oracle.
Seul autre écart, voulu, de la Slice 04 : `[qa]` et `[research-lead]` sont désormais des rôles annoncés (lus,
consommés du libellé, loadout `reviewer` et `research`) ; l'oracle « activé » du même test le fige, et sans ces
deux marqueurs l'ancien oracle reste exact.

Le suivi des tâches garde la description sans le seul marqueur éphémère (`[code] [coder] Corriger…`), pour
que le rôle s'y relise comme le hook le lit (`task_snapshot["role"]`).

### Déclaration transmise à Core (D25)

`agent_markers.declaration_from_hook_event(event)` rend une `AgentDeclaration` : profil, rôle résolu
(`role_id`, `role_marker`, `role_status`), drapeau éphémère, libellé, `tool_use_id` et `caller_agent_id`
(l'`agent_id` du sous-agent appelant, présent pour un appel imbriqué). `to_payload()` en est la forme
stable. Le hook `PreToolUse` est la source de ces faits pour Core ; le parsing du flux `stream-json`
reste un affichage diagnostique. Depuis la Slice 05, le hook dépose `AgentDeclarationFact` (avec la mission
décidée) dans le registre local, que le Control Center relaie à Core
([agent-orchestration.md](agent-orchestration.md) §5). Un mot inconnu n'est pas un rôle : la déclaration
porte `undeclared`, jamais `unknown` (réservé à un id de forme valide que le registre ne connaît pas).

## 3. Missions et sous-missions

`missions.Mission` : un objectif dont une instance répond.

- `mission_id` stable ; `parent_mission_id` pour une sous-mission ; `root_mission_id` (la mission elle-même
  pour une racine, exigé pour une sous-mission) ;
- `objective` (1 000 caractères au plus), `origin_kind` facultatif (nature de la demande quand elle est
  connue : `code`, `research`, `design`…) ;
- `dossier_path` : référence par chemin au dossier de mission partagé
  `missions/<sujet-court>-<AAAAMMJJ>/mission.md` de la mémoire du Board (`MISSION_PATH_HINT`). La mission
  ne crée pas un second support de prose ;
- `owner_instance_id` : le propriétaire courant ;
- cycle de vie `open` -> `completed | cancelled | failed` (`Mission.close`), une seule fois. C'est le sort de
  l'objectif, pas le statut des agents : une mission reste ouverte pendant que ses agents finissent,
  échouent ou sont relancés.

`check_mission_tree(missions, instances)` vérifie un ensemble complet : ids uniques, parents présents,
aucune boucle, profondeur au plus `MAX_MISSION_DEPTH` (16), racine déclarée égale à la racine réelle,
propriétaire de chaque mission Mission Owner de celle-ci.

Aucun plan n'y est représentable : une sous-mission n'existe que lorsqu'un propriétaire l'a réellement
créée (D15).

## 4. Instances d'agent

`missions.AgentInstance` : une instance telle que la mission la connaît.

- `instance_id`, et l'identité Work State `(work_source, work_external_id)` : la clé de jointure stable
  (`AgentTask.work_key` côté Claude, le `tool_use_id` initial, pas l'id qui change en cours de vie) ;
- `role_id` (id canonique, ou `undeclared`), `role_marker` (le marqueur tel qu'écrit, provenance) ;
- `ephemeral`, `mission_id`, `mission_owner`, `parent_instance_id`, `label`, `created_at`.

**Aucun statut d'exécution** : progression, statut et fin vivent dans Core Work State (D16), lus par
`work_identity`.

**Immuabilité.** `role_id`, `role_marker`, `ephemeral`, `mission_id`, `mission_owner`,
`parent_instance_id` et l'identité Work State sont posés une fois (`IMMUTABLE_INSTANCE_FIELDS`).
`reconcile_instance(current, incoming)` accepte une seconde déclaration identique (rejeu, redémarrage) et
peut seulement compléter un libellé vide ; toute autre différence lève `MissionError` de code
`immutable_field`, nommant le champ. Changer de rôle ou de contexte, c'est une **nouvelle instance** (D14,
relais : [agent-relations.md](agent-relations.md) §4).

Un rôle que le registre ne connaît plus reste tel quel dans l'instance : `role_known` est faux et
l'affichage dégrade, rien n'est réécrit.

`instance_from_declaration` construit une instance depuis une `AgentDeclaration`, rôle et éphémère tels que
déclarés.

## 5. Mission Owner

Mission Owner est un **statut d'instance** (`AgentInstance.mission_owner`), pas un rôle (D03) : un
Développement ou une Direction de recherche peut porter une mission en gardant son rôle.

- Il exige une mission (`mission_id`) et un rôle capable (`can_own_mission`), sinon
  `role_cannot_own_mission`.
- **Qui le devient** (Slice 05) : un agent d'un rôle capable lancé par le cerveau (mission racine, objectif =
  libellé) ou lancé avec `[mission]` par un autre agent (sous-mission de la mission de l'appelant). Tout autre
  agent est membre de la mission de son appelant. Le hook lui appose « RESPONSABILITÉ DE MISSION (JARVIS) » ;
  sa mission se clôt avec la fin de son travail ([agent-orchestration.md](agent-orchestration.md)).
- Il est récursif (D04) : le propriétaire d'une sous-mission est une instance Mission Owner de cette
  sous-mission, qui peut à son tour organiser sa propre équipe ; le propriétaire de la mission parente garde
  le résultat d'ensemble. Le contrat impose la cohérence (pas de boucle, propriétaire de la bonne mission),
  pas qui a lancé qui : `parent_instance_id` le dit, tel qu'observé.
- Il ne change de main que par un relais explicite : `transfer_ownership(mission, successor, handoff_ref=…)`
  exige l'id du relais et un successeur Mission Owner de la même mission ; une mission close ne change plus
  de propriétaire.

### 5bis. Restitution du Mission Owner (Slice 11)

Décision D23 du handoff jarvis-organic-agent-orchestration : un rapport ou une comparaison sérieuse se livre
sur une surface riche **existante**, une réponse simple reste simple. Politique : module pur
`jarvis/domain/delivery_quality.py` ; tests `tests/unit/test_delivery_quality.py`.

**Ce que le hook appose, et où.** Au Mission Owner seulement (ni membre, ni agent sans mission), une seule fois :

1. dans la charte, juste après sa consigne de compte rendu (« Compte rendu court… »), la ligne
   `delivery_quality.REPORT_NOTE` (`agent_charter.sign_brief(report_note=)`, première occurrence, le texte de la
   charte ne change pas) : un résultat structuré s'affiche ; le compte rendu en donne l'`object_id` et la
   conclusion, pas la synthèse entière ;
2. la méthode de `research-lead` dit la même chose dans son « COMPTE RENDU » (quand il porte la mission) ;
3. en tête du bloc « RESPONSABILITÉ DE MISSION (JARVIS) » (`agent_orchestration.mission_brief`), juste après sa
   portée, le paragraphe « RESTITUTION (JARVIS) » (`delivery_quality.delivery_brief`). Il était d'abord en fin de
   consigne, où il pesait moins que les consignes de compte rendu de la charte et de la méthode (reprise QA B2).

Ordre réel vérifié par test sur l'assemblage du hook : charte (compte rendu, puis la note) → consigne → méthode du
rôle → bloc de mission (restitution, puis le reste). Le paragraphe dit :

- pourquoi : l'utilisateur ne lit pas le compte rendu d'un sous-agent, le cerveau vocal le lui résume ; ce qui
  doit être relu n'atteint l'utilisateur que s'il est affiché ;
- **une règle de jugement sur le résultat réel**, une fois obtenu, jamais sur les mots de la demande : un
  résultat qui tient en une ou deux phrases se dit, sans fenêtre ; un résultat structuré (plusieurs options ou
  critères à comparer, rapport, état des lieux, bilan, audit, synthèse de recherche, explication détaillée,
  liste d'actions, tout ce que l'utilisateur voudra relire) s'affiche par la surface adaptée : `jarvis.table`
  (recommandation longue dans un `jarvis.document` à côté), `jarvis.document`, `jarvis.checklist`, ou une
  surface plus riche trouvée par `prefab_search` ;
- toutes les bornes réelles des `data` : tableau 8 colonnes, intitulés ≤ 40 caractères, 64 lignes, 8 cellules par
  ligne, cellules de type chaîne ≤ 200 ; document Markdown ≤ 12000 ; checklist 64 éléments, `id` ≤ 64, `label`
  ≤ 200, `note` ≤ 500. Recopiées de la dernière version livrée des manifestes, égalité vérifiée par test ;
- comment : `mcp__jarvis-display__scene_create_object` (kind `window`, `prefab {prefab_id, data}`), chargé par
  `ToolSearch` s'il est différé ;
- quand la livraison est faite : seulement si l'outil rend un `object_id`. Sur refus, erreur ou outils absents,
  suivre le repli : ne jamais dire affiché ce qui ne l'est pas, livrer en Markdown structuré, une phrase sur
  l'échec ;
- après un affichage réussi : l'`object_id` et la conclusion, sans recopier l'affiché.

Aucun indice tiré des mots de la demande (arbitrage de l'agent 0 : l'heuristique par mots-clés de la première
version classait juste 46 % d'un corpus de 64 demandes réalistes ; retirée). Ni gabarit imposé, ni nombre
d'artefacts, ni doctrine de complexité minimale (D05) ; le Mission Owner juge aussi la suffisance des preuves
avant de rendre (D22, même bloc).

**Repli d'un affichage qui échoue.** `SceneDisplayTools.create_object` / `update_object` avec un argument
`prefab` : toute `DisplayToolError` garde son code et sa phrase et reçoit `delivery_quality.fallback_note`
(« REPLI DE RESTITUTION (JARVIS) »), qui dit **l'état réel de l'écran** (`screen_state`) :

| Échec | Ce que dit la note |
| --- | --- |
| création refusée (`prefab_invalid`, `unknown_prefab`, `prefab_unavailable`, `invalid_argument`, commande non envoyée…) | la fenêtre n'a pas été créée, rien de nouveau n'est à l'écran |
| mise à jour refusée (mêmes codes) | la mise à jour n'est pas appliquée, la fenêtre `<object_id>` garde son contenu précédent |
| mise à jour d'un objet inconnu ou archivé (motif `unknown_object` / `object_archived`) | aucune fenêtre `<object_id>` n'existe, rien n'est affiché sous ce nom |
| panne de transport, réponse illisible ou erreur HTTP de Core hors 400/413 (`UNKNOWN_OUTCOME_CODES` : `core_timeout`, `core_unreachable`, `core_bad_answer`, `invalid_scene_response`, `core_refused`, `display_internal_error`) | l'état de l'affichage est inconnu : relire la scène avant d'en parler ou de réessayer |

Pourquoi un refus est sûr : il est décidé avant l'envoi (argument, taille, prefab, délégation), la commande n'est
pas partie (`command_not_sent`), ou Core répond sans appliquer : refus du domaine dans une réponse 200
(`scene_refused`), 400/413, ou 503 de scène (`scene_unavailable`, `scene_persist_failed`, « Rien n'a été
appliqué »). `core_refused` couvre toute autre erreur HTTP de Core, 5xx compris ; le statut ne remonte pas
jusqu'à la note et une erreur interne après application ne peut pas être exclue, d'où « inconnu ».
`protocol_error` n'est levé que par un lot, jamais par une création ou une mise à jour. Un `prefab` sans
`prefab_id` (absent ou vide) est refusé avant tout envoi (`invalid_argument`), jamais « inconnu ».

Pour un refus, corriger les données et réessayer reste permis : la remarque `scene_changed` éventuelle porte sur
d'autres objets. Puis le prefab visé et le contenu prêt à livrer (`readable_content` : tableau Markdown pour
`jarvis.table`, corps pour `jarvis.document`/`window`/`browser`, cases pour `jarvis.checklist`, JSON indenté
sinon ; borné à 4000 caractères, coupure dite), présenté comme une forme écrite « à résumer à l'oral au lieu de
la lire ». Un argument sans `prefab_id` reçoit une note propre, sans contenu. La note est **neutre vis-à-vis de
l'appelant** : le serveur ne distingue pas le cerveau d'un sous-agent (même acteur `brain`), elle ne parle donc ni
de compte rendu ni d'une consigne propre à un sous-agent. L'échec reste journalisé une fois
(`display.tool_refused` ou `display.tool_failed`) ; `display.prefab_fallback` (info : outil, code, motif,
`prefab_id`, jamais le contenu) dit qu'un repli a été proposé. Un échec sans `prefab` est inchangé. Le journal
`agent.event` du cerveau recopie le résultat d'outil entier (comportement préexistant, hors de ce module) : la
borne de 4000 caractères limite ce qu'il y gagne.

**Voie réelle de livraison** (bacs à sable du 2026-10-20, CLI 2.1.304, haiku) : un sous-agent `general-purpose`
lancé par le cerveau a les outils `jarvis-display` du cerveau, différés (`deferred_tools_delta`), chargés par
`ToolSearch` ; ses appels sont journalisés avec l'acteur `brain` (aucune distinction d'acteur pour un
sous-agent). Sans `scene.enabled`, le serveur n'est pas déclaré : le Mission Owner livre en Markdown.

**Limite.** Seul un Mission Owner reçoit la consigne. Depuis la Slice 07 le cerveau confie une comparaison ou
un état des lieux sérieux à `[general] [research-lead]`, qui porte la mission ; une recherche ciblée confiée à
`[research]` (rôle qui ne porte pas de mission) ne la reçoit pas, et c'est voulu. Le cerveau connaît le contrat
(section 9) : il ne traite pas une fenêtre affichée par un Mission Owner de « non demandée » et ne lit pas un
tableau à voix haute. La beauté du rendu reste un jugement humain
(`HV-ORG-11-01`, `HV-ORG-11-02`).

## 6. Éphémère

Un seul drapeau (décision I-004 de l'agent 0, 2026-10-20) : une tâche courte dont la réussite est
silencieuse et qui ne reste pas dans l'historique durable.

- **Déclaré**, jamais déduit d'une durée : marqueur `[éphémère]` (section 2), puis `ephemeral` sur
  `WorkObservation`/`WorkItem` et sur `AgentInstance`. Aucun champ de durée n'entre dans la décision.
- **Posé une fois** sur l'instance. Une tâche éphémère peut porter un rôle (`[éphémère] [code] [coder]
  Corriger la coquille`).
- **Rabaissé sur échec**, comme aujourd'hui : `missions.retained_in_history(instance, status)` est vrai pour
  une instance ordinaire, et pour une éphémère dès que son statut Work State sort de
  `EPHEMERAL_WORK_STATUSES` (échec, arrêt, interruption, blocage). Une tâche ne meurt jamais en silence.
- Une instance éphémère **ne porte pas de mission** (`ephemeral_mission_owner`) : la mission resterait
  orpheline d'un historique qui ne la garde pas.

La règle du prompt du cerveau qui dit quand déclarer une éphémère (`claude_local.py`, « Tâche éphémère »)
couvre depuis la Slice 07 les petites corrections évidentes dont le changement visible suffit comme compte
rendu (une coquille, une erreur évidente que l'utilisateur vient de montrer : `[éphémère] [code] [coder] …`).
Un correctif dont l'utilisateur attend la confirmation reste une tâche ordinaire à un seul agent ; au
lancement, le cerveau ne promet pas de compte rendu ; un échec est toujours annoncé. Toujours un seul drapeau
(I-004).

## 7. Ce qui reste à câbler

| Sujet | Où |
| --- | --- |
| Contrat de la déclaration du hook (`AgentDeclarationFact`), `role_id` de `WorkObservation`, historique durable : faits ([mission-history.md](mission-history.md)) | Slice 03 |
| Câblage du hook vers Core, outils du Mission Owner (`[mission]`, méthode choisie, `SendMessage`/`TaskStop`), `can_spawn` mécanique, charte consciente du rôle | fait (Slice 05, [agent-orchestration.md](agent-orchestration.md)) |
| Relations au runtime (communication, QA, adversaire, relais) | Slice 06 |
| Règles du cerveau (rôles proposés : `offered_to_brain` de `research-lead` et `qa`, éphémère élargie, `[mission]` enseigné au cerveau) | fait (Slice 07, section 9) |
| Rôle dans la scène, badge Mission Owner | Slice 08 |

## 8. Interface : Réglages > Sous-agents

Onglet `subagents` des Réglages du Control Center (Slice 10), après « Mémoire ». Module
`jarvis/runtime/control_center_subagents_settings.js` (`window.JarvisSubagentSettings`), monté par
`renderTab` dans `#subagentSettingsMount`, détruit par `cleanupSettingsSurface` au changement d'onglet.
Tests : `tests/unit/test_control_center_subagents_settings_js.py` (node, sur la vraie charge utile v2).

**Sources.** Lecture seule de `GET /api/subagent-roles` (section 1ter) pour le catalogue, et de
`GET /api/agent/tasks` (champ `role`, le marqueur tel que le hook le lit) pour les instances en cours. Aucune
autre donnée, aucune liste recopiée : libellés, capacités, méthodes, libellés de relation
(`relation_labels`) et jetons viennent de la route.

**Ce que montre l'écran.**

- Une liste des rôles (icône, badge, libellé, marqueur, étiquettes `modifié`, `non enregistré`,
  `surcharge écartée`, `Désactivé`), parcourable aux flèches haut/bas, Début et Fin ;
- la fiche du rôle choisi : description, mission, quand l'employer, marqueur `[profil] [id]`, alias,
  disponibilité (`enabled`, `offered_to_brain`, `offered_to_subagents`), capacités (lance des agents,
  Mission Owner, réponse imposée `constrained_output`, outils, savoirs `loadout_role`, skills, profil),
  Work Methods (celle par défaut d'abord, « par défaut, apposée » ; les autres « suggestion » ; principes,
  critères et relations derrière une divulgation) ;
- **l'ordre de la consigne apposée** (section 1bis) : 1. vos instructions (modifiable), 2. capacités du rôle
  (générées), 3. Work Method par défaut (non modifiable). L'écran dit en toutes lettres que la méthode
  s'ajoute **après** les instructions éditables et suit le code ;
- les instructions, repliées derrière « Afficher et modifier les instructions (N caractères) » : jamais un mur
  de texte en premier plan ;
- les instances en cours, dans une zone repliable sous la liste (« Instances en cours » et leur nombre) : rôle
  résolu comme `resolve_role` (déclaré, alias avec son marqueur, désactivé ; un alias dont la cible manque à la
  liste reste un alias, nommé avec sa cible), « Marqueur hors registre » pour un mot inconnu, « Général, aucun
  rôle déclaré » sans marqueur, étiquette éphémère. Seules les clés propres de `aliases` comptent
  (`constructor` n'est pas un alias) ;
- un renvoi vers « Agent / CLI › Sous-agents / Modèles », qui règle les modèles des sous-agents.

**Identité visuelle.** `visual.accent` est un jeton : il devient `var(--role-accent-<jeton>)`, défini une
seule fois dans `control_center.html` pour les dix jetons de `ROLE_ACCENTS` (table partagée avec le graphe des
tâches). Un jeton absent de `accents` retombe sur `slate` et est journalisé une fois
(`subagent_settings_unknown_accent`). L'icône (`visual.icon`, pictogramme dessiné ; silhouette générique pour
un jeton inconnu) et le badge accompagnent toujours la couleur. Le module ne contient aucune couleur (test).

**Compteur.** « n / 8 192 caractères », la borne lue dans `instructions_max_chars` (à défaut la constante
`DEFAULT_MAX_CHARS` du module, égale à `MAX_OVERRIDE_TEXT`) ; au-delà, le bouton Enregistrer se désactive.

**Seule écriture : les instructions.** `POST /api/prompts/subagent_role.<id>` existant :
`{action: "edit", text, base_revision: default_revision, expected_effective_revision: revision}` ou
`{action: "reset"}` (confirmation en deux temps). Après succès, la route est relue et l'écran dit que le
texte s'applique au prochain sous-agent lancé avec ce rôle. Si la réponse porte
`subagent_roles_snapshot.written: false`, l'écran dit que le texte est enregistré mais pas encore transmis au
hook. Capacités et méthodes sont marquées « lecture seule » : aucune voie d'écriture n'existe pour elles.

**États.**

| État | Ce qui s'affiche |
| --- | --- |
| chargement | pictogramme animé, « Lecture du registre des rôles… », compteur en secondes, échéance (15 s) |
| erreur de lecture | alerte « Réponse : « … ». », le code, « Rien n'a été modifié », un conseil propre à la cause (document `prompt_overrides` illisible pour un code `prompt_*`, réponse d'une autre version, Control Center injoignable), bouton Réessayer ; console `subagent_settings_load_failed` |
| échéance dépassée | « Pas de réponse du Control Center après 15 s. » (`subagent_settings_timeout`) |
| registre vide | « Aucun rôle dans le registre » : les sous-agents s'exécutent comme agents généraux |
| rôle désactivé | nom barré dans la liste, étiquette Désactivé, explication dans la fiche |
| actif mais pas proposé au cerveau | note dans la fiche (aujourd'hui `research-lead`, `qa`) |
| surcharge écartée (`conflict`) | alerte : le défaut s'applique, réenregistrer pour la reprendre |
| écriture réussie, relecture en échec | « Enregistré ; la relecture a échoué : « … ». », bouton « Réessayer la relecture » ; jamais « Rien n'a été écrit » ; console `subagent_settings_refresh_failed` |
| écriture sans réponse (échéance de 15 s, ou serveur injoignable) | « Résultat inconnu : … Relisez avant de réenregistrer. », relecture immédiate, puis ce qu'elle montre : modification enregistrée (brouillon retiré) ou version précédente (texte gardé dans le champ) |
| charge utile partielle ou d'une autre version | avertissement de version, entrées sans `id` ignorées et comptées, « Fiche incomplète » qui nomme les champs absents (affichés vides), enregistrement désactivé sans révisions |
| exception d'affichage | état d'erreur `subagent_settings_render_failed` avec Réessayer, jamais un écran figé ; le montage de l'onglet intercepte aussi `load()` (`subagent_settings_mount_failed`) |
| conflit de révision (`prompt_override_concurrent`, `prompt_override_stale`) | alerte : la version a changé ailleurs, **le texte de l'utilisateur reste dans le champ**, les révisions sont relues ; un second enregistrement, voulu, remplace la version enregistrée |
| refus d'enregistrement (réponse d'erreur du serveur) | « Enregistrement refusé. Refus du serveur : « … ». Rien n'a été écrit. », le code, brouillon gardé ; console `subagent_settings_save_failed` |
| instances illisibles | alerte locale ; le catalogue reste utilisable ; console `subagent_settings_tasks_failed` |

Les brouillons vivent dans `SET.subagentDrafts` : changer d'onglet des Réglages ne perd pas un texte non
enregistré (fermer la page, si). Le chemin normal est journalisé en console à `info`
(`subagent_settings.loaded`, `subagent_settings.instructions_edit|reset`) ; le serveur journalise
`prompt.override.*` et `subagent_roles.snapshot_*`. Le Control Center n'a pas de route d'écriture des erreurs
du navigateur : les échecs du navigateur restent en console et à l'écran.

**Accessibilité et largeur.** La fiche n'est pas une région live : une région courte, hors du rendu, annonce
seulement les notices. En couleurs forcées, la sélection est marquée par une bordure épaisse `Highlight` et
un soulignement, pas par la couleur. Sous 900 px, une seule colonne : choisir un rôle amène la fiche à l'écran,
focus sur son titre, avec « Revenir à la liste des rôles ». La barre d'onglets des Réglages ramène l'onglet actif
dans la vue (pour tous les onglets). Le pied de la modale est masqué dans cet onglet, qui porte ses propres
notices. Les couleurs du CSS `.sar-*` sont des jetons du thème (`--text`, `--muted`, `--solid`, `--line`,
`--accent`, `--role-accent-*`).

**Thèmes.** Lisible dans les deux thèmes livrés (Circuit imprimé, Cosmos), tous deux sombres, et en couleurs
forcées (contraste élevé de Windows). Le Control Center n'a pas de thème clair.

## 9. Ce que le cerveau sait des rôles (Slice 07)

Le cerveau vocal ne lit qu'une section générée du registre, `brain_rules()` (« TYPE DE DEMANDE », dans
`BRAIN_SYSTEM_PROMPT`), plus des règles voisines de `claude_local.py` (consigne, notification, « Tâche
éphémère », FORMAT ORAL) et `routing_hook.PROFILE_RULE`. Ce qu'elles enseignent :

- **Catalogue** : chaque rôle proposé (`offered_to_brain`) avec son marqueur `[profil] [rôle]` et son
  `when_relevant`. Quand la direction de recherche est proposée, la recherche web porte un renvoi généré : « pas
  pour comparer ou conseiller entre options : [general] [research-lead] » (haiku confiait « lequel me
  conseillez-vous » à la recherche web). `qa` : « relecture d'un résultat déjà produit » (un relecteur lancé par le cerveau n'a pas
  de mission, donc pas de relation QA : `relation_no_mission`). Aucun exemple de Work Method : le cerveau ne
  voit pas leur liste (un exemple à trois crochets a fait écrire `[general] [web-research] [research-lead]` à
  haiku) ; le choix d'une méthode reste aux Mission Owners.
- **A. Action claire** : un seul agent du bon rôle, ou une éphémère pour une petite correction évidente. Ni
  Intervieweur ni plan préalable : l'agent juge lui-même s'il lui faut de l'aide (organique, D05/D07/D19).
- **B. Intention à cadrer** : dans son tour, le cerveau n'écrit ni ne vérifie rien. Il compose sans outil le
  chemin absolu du dossier de mission, `missions/<sujet-court>-<AAAAMMJJ>/mission.md` sous la ligne « Mémoire
  du Board (boards/<id>/memory) : <chemin absolu> » de son contexte de tour (`board_brief.render_board_memory`),
  et le donne à l'Intervieweur, **seul agent lancé à ce tour**, qui le crée (`_DOSSIER`). Les recherches utiles
  partent au tour de notification de sa première `QUESTION :`, une fois le dossier créé, avec le même chemin, et y
  versent leurs apports (plus de course d'écriture sur `mission.md`) ; la réponse de l'utilisateur repart par `SendMessage` avec en une ligne chaque trouvaille
  arrivée depuis la dernière question (D20). Le tour de console `/api/agent/send` ne porte pas ce contexte : le
  chemin n'y est pas composable.
- **C. Comparer, choisir, faire l'état d'un sujet** : un seul `[general] [research-lead]`, qui porte la mission.
- **Second regard, concurrence, relais** : `[code] [coder]` et `[general] [research-lead]`, lancés par le
  cerveau, sont Mission Owners ; eux seuls organisent une QA, des approches concurrentes (une consigne différente
  par producteur) ou un relais, et tranchent (le cerveau n'a que `relation_read`, `BRAIN_WORKSPACE_PROMPT`).
  Travail en cours : le cerveau le demande à son Mission Owner par `SendMessage` ; demande neuve : il lance un
  seul Mission Owner avec les mots de l'utilisateur. Seule exception : la relecture d'un résultat déjà rendu,
  hors de toute mission en cours, part directement chez `[general] [qa]` (`[code] [qa]` pour du code).
- **Restitution** (contrat de la section 5bis), dans la règle de notification, là où se joue le tour de fin :
  relais en une à trois phrases, sans markdown, la conclusion d'abord, même quand rien n'est affiché (le reste du
  compte rendu ne se lit pas) ; si l'agent a affiché son résultat (voulu : jamais « non demandé », n'en demande pas
  le retrait), la conclusion et « le détail est affiché », sans lire de liste ni de tableau.
- **Consigne** : les mots exacts de l'utilisateur, l'observable, où chercher, ce qui a été refusé ; jamais la
  forme, la longueur ni le support du **résultat final** (fichier, format, nombre de phrases) : JARVIS les donne
  (charte, rôle, restitution). Le dossier de mission du cas B est un support de cadrage voulu ; hors de lui, le
  cerveau ne prescrit aucun nom de fichier. Une consigne « écris le rapport dans un fichier, conclusion en trois phrases » a empêché
  l'affichage d'un Mission Owner en essai réel.
- **Une seule règle de longueur** (FORMAT ORAL) : lancement et résumé avant accord en une phrase ; toute autre
  réponse, relais compris, en trois phrases au plus ; pas de markdown. Une éphémère : la phrase de lancement ne
  promet rien (pas de « je vous dirai »).
- **Présentation** : le cerveau lance un seul auteur ; une relecture demandée se fait par l'auteur
  (`[general] [presentation-review]`), plus par le cerveau.
- **Passage à l'exécution** : `EXECUTION_GATE_RULE`, inchangée, seulement pour le cas B (après `PRÊT :`,
  accord oral). Aucune porte nouvelle (D21, I-003) ; un test vérifie qu'elle est la seule.

**Décision `[reviewer]` (Slice 07).** `PROFILE_RULE` enseigne `[qa]` pour une relecture (`[code] [qa] …`) :
même rôle, même méthode, même loadout `reviewer` que l'alias. `[reviewer]` n'est plus enseigné nulle part au
cerveau mais reste lu (alias) ; condition de retrait :
[legacy/subagent-role-aliases.md](legacy/subagent-role-aliases.md).

**Second mot de rôle.** `[general] [web-research] [research-lead] …` se lit toujours `web-research`, le second
mot restant dans le libellé (grammaire inchangée, `test_agent_markers_equivalence`). Le hook le consigne :
`agent.role_applied` au niveau `warning`, `second_role_marker` = le mot, `diagnostics` = `["second_role_marker"]`
(`agent_markers.second_role_marker`). L'appel n'est jamais refusé.

Taille : `BRAIN_SYSTEM_PROMPT` 8 880 → 11 300 (première passe) → 10 661 (reprise QA) → 11 082 caractères
(revérification) ; `brain_rules()` 2 412 → 3 550 → 3 648 (empreinte dans `tests/unit/test_scene_artifacts.py`). Une conversation ouverte
avant ce changement garde l'ancienne consigne jusqu'au redémarrage de JARVIS (`--system-prompt-snapshot`).
