# Rôles de sous-agent, missions et Mission Owner

Page canonique des rôles de sous-agent, des marqueurs que le cerveau écrit pour les déclarer, des missions
et des instances d'agent. Elle décrit le contrat ; le câblage d'exécution (lancement, persistance,
affichage) est signalé là où il manque encore.

| Contrat | Code | Tests |
| --- | --- | --- |
| Registre des rôles, résolution des marqueurs, ce que le hook appose | `jarvis/domain/subagent_roles.py` | `tests/unit/test_subagent_roles.py` |
| Hook `PreToolUse` (méthode, loadout, journal `agent.role_applied`) | `jarvis/runtime/routing_hook.py` | `tests/unit/test_subagent_roles.py`, `tests/unit/test_routing_hook.py` |
| Lecture du registre pour Settings (`GET /api/subagent-roles`) | `jarvis/runtime/control_center.py` (`_subagent_roles_payload`) | `tests/unit/test_subagent_roles.py` |
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
| `research-lead` | Direction de recherche | Research Lead | general | oui | oui | `research` | **deep**, comparative, quick | compass, indigo, DIR | **non** (Slice 07) | oui |
| `qa` | Contrôle qualité | QA / Quality Analyst | general | non | non | `reviewer` | **result-review**, bug-investigation | shield-check, lime, QA | **non** (Slice 07) | oui |

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
    `research-lead` et `qa` sont actifs depuis la Slice 04 mais **pas encore proposés au cerveau** : la règle
    qui dit au cerveau quand les lancer appartient à la Slice 07, qui passera ce drapeau à vrai. Le prompt du
    cerveau est donc inchangé octet pour octet (`test_scene_artifacts.BASE_SYSTEM_SHA256`) ;
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
  `[general] [research-lead]` et obtient la bonne méthode ; l'alias historique `[code] [reviewer]` que
  `PROFILE_RULE` enseigne déjà au cerveau reçoit la méthode du Contrôle qualité.
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
  `tools`, et réciproquement : le spawn imbriqué est prouvé sur le CLI installé, mais un type d'agent à
  outils restreints sans `Agent` ne pourrait pas lancer, d'où l'obligation de les garder d'accord.
- `work_methods` / `default_work_method` : ids de [Work Methods](work-methods.md) livrées
  (`work_methods.BUILTIN_METHODS`) permises et celle proposée par défaut. Vérifié au chargement du module :
  un rôle ne cite qu'une méthode livrée qui s'applique à lui (`check_role_methods`), et une méthode ne vise
  que des rôles du registre. Seule la méthode par défaut est apposée sur la consigne ; les autres sont des
  suggestions lisibles dans Settings, qu'un Mission Owner pourra choisir (Slice 05). Les rôles existants
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
| `reserved_role_ids` | `undeclared`, `unknown` : à afficher comme rôle général ou inconnu, jamais deviné |
| `execution_gate`, `mission_path`, `application` | inchangés depuis la version 1 |

Version 2 n'ajoute que des clés : un lecteur de la version 1 lit la même chose. Une valeur existante change
depuis la Slice 01 : `coder.tools` contient `Agent`.

## 2. Les marqueurs de tête d'un appel `Agent`

L'outil `Agent` appartient au CLI : le cerveau ne peut pas lui ajouter de paramètre. Il déclare ce que
JARVIS doit savoir d'un sous-agent par des marqueurs entre crochets en tête de la `description`. Une seule
grammaire, `agent_markers.parse_head`, lue à l'identique par le hook `PreToolUse`
(`jarvis/runtime/routing_hook.py`) et par le suivi des tâches (`jarvis/runtime/agent_tasks.py`).

- La **tête** est la suite des groupes entre crochets au début du texte, au plus quatre : trois mots et le
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
reste un affichage diagnostique. Le transport vers Core relève des Slices 03 (contrat) et 05 (câblage) :
aujourd'hui le hook ne l'émet pas encore.

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
- Il est récursif (D04) : le propriétaire d'une sous-mission est une instance Mission Owner de cette
  sous-mission, qui peut à son tour organiser sa propre équipe ; le propriétaire de la mission parente garde
  le résultat d'ensemble. Le contrat impose la cohérence (pas de boucle, propriétaire de la bonne mission),
  pas qui a lancé qui : `parent_instance_id` le dit, tel qu'observé.
- Il ne change de main que par un relais explicite : `transfer_ownership(mission, successor, handoff_ref=…)`
  exige l'id du relais et un successeur Mission Owner de la même mission ; une mission close ne change plus
  de propriétaire.

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
n'est pas modifiée par ce contrat ; son élargissement aux petites corrections évidentes relève de la
Slice 07.

## 7. Ce qui reste à câbler

| Sujet | Où |
| --- | --- |
| Contrat de la déclaration du hook (`AgentDeclarationFact`), `role_id` de `WorkObservation`, historique durable : faits ([mission-history.md](mission-history.md)) | Slice 03 |
| Câblage du hook vers Core (le Control Center joint le fait à la tâche et le remet à Core) | Slice 05 |
| Outils d'orchestration du Mission Owner (spawn, délégation, relais) | Slice 05 |
| Règles du cerveau (rôles proposés : `offered_to_brain` de `research-lead` et `qa`, éphémère élargie) | Slice 07 |
| `can_spawn` mécanique (type d'agent à outils réduits), choix d'une Work Method autre que celle par défaut | Slice 05 |
| Rôle dans la scène, badge Mission Owner | Slice 08 |
| Onglet Settings > Sous-agents | Slice 10 |
