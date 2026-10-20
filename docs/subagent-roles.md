# Rôles de sous-agent, missions et Mission Owner

Page canonique des rôles de sous-agent, des marqueurs que le cerveau écrit pour les déclarer, des missions
et des instances d'agent. Elle décrit le contrat ; le câblage d'exécution (lancement, persistance,
affichage) est signalé là où il manque encore.

| Contrat | Code | Tests |
| --- | --- | --- |
| Registre des rôles, résolution des marqueurs | `jarvis/domain/subagent_roles.py` | `tests/unit/test_subagent_roles.py` |
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

| id = marqueur | Libellé | Nom dans le handoff | Profil | Mission Owner | Lance des agents | Loadout | Visuel (icône, accent, badge) | Actif |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `interviewer` | Intervieweur | Interviewer | general | non | non | profil | question, violet, INT | oui |
| `research` | Recherche documentaire | Document Research | general | non | non | `research` | book, teal, DOC | oui |
| `web-research` | Recherche web | Web Research | general | non | non | profil | globe, sky, WEB | oui |
| `coder` | Développement | Developer | code | oui | oui | `coder` | code, amber, DEV | oui |
| `concept` | Conceptualisation | Conceptualizer | general | non | non | profil | lightbulb, rose, CPT | oui |
| `research-lead` | Direction de recherche | Research Lead | general | oui | oui | profil | compass, indigo, DIR | **non** |
| `qa` | Contrôle qualité | QA / Quality Analyst | general | non | non | `reviewer` | shield-check, lime, QA | **non** |

Règles :

- **Les ids ne changent pas.** Les cinq premiers indexent les surcharges d'instructions déjà enregistrées par
  l'utilisateur (prompt `subagent_role.<id>`, Settings > Sous-agents) ; les renommer les rendrait orphelines.
  Un nouveau rôle reçoit un nouvel id, additif.
- **Les ids sont des données explicites**, jamais déduits d'un libellé : « Développeur : corriger le bug »
  ne déclare aucun rôle.
- `research-lead` et `qa` sont définis mais **désactivés** (`enabled=False`) tant que leur câblage n'est pas
  livré : méthode et loadout (Slice 04), règles du cerveau (Slice 07). Désactivé, un rôle n'apparaît pas
  dans la section « TYPE DE DEMANDE » du cerveau (`brain_rules`), le hook n'appose pas sa méthode, et son
  marqueur **n'est pas annoncé** (absent de `agent_markers.ANNOUNCED_ROLES`) : `[code] [qa] …` se lit
  exactement comme avant que le rôle existe — `[qa]` n'est pas consommé, reste dans le libellé, ne masque
  pas le rôle de la consigne et ne change pas le loadout. Seul un appel direct à `resolve_role("qa")` rend le
  statut `disabled`. L'activation se fait dans la Slice qui le câble, avec ses tests.
- Mission Owner **n'est pas un rôle** (section 5). Il n'existe ni rôle « Orchestrateur » ni rôle
  « Owner ».

### Alias de compatibilité

`subagent_roles.ROLE_ALIASES` relie un marqueur historique à l'id qu'il désigne :

| Alias | Rôle | Pourquoi |
| --- | --- | --- |
| `reviewer` | `qa` | rôle de loadout historique de la relecture (`memory_settings.LOADOUT_ROLES`) |

`coder` et `research` n'ont pas besoin d'alias : ce sont à la fois des rôles du registre et des rôles de
loadout. Un alias n'est pas un rôle (`role_by_id("reviewer")` est `None`) et le hook continue de lire
`[code] [reviewer]` comme la clé de loadout `code:reviewer`, comme avant. Condition de retrait de l'alias :
[legacy/subagent-role-aliases.md](legacy/subagent-role-aliases.md).

### Résolution d'un marqueur

`resolve_role(marker) -> RoleResolution(role_id, marker, status)` est déterministe et ne lève jamais :

| Marqueur | `role_id` | `status` |
| --- | --- | --- |
| absent ou vide | `undeclared` | `undeclared` |
| marqueur d'un rôle actif (`coder`, casse ignorée) | son id | `declared` |
| marqueur d'un rôle désactivé (`qa`) | son id | `disabled` |
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
- `work_methods` / `default_work_method` : ids de [Work Methods](work-methods.md) permises et celle proposée
  par défaut. Vides aujourd'hui : le catalogue est la Slice 04 (`work_methods.check_role_methods` vérifiera
  les références).
- `loadout_role` : rôle de loadout (`LOADOUT_ROLES`) dont l'instance prend les savoirs, ou rien (le loadout
  du profil). Aujourd'hui le hook lit le loadout sur le marqueur ; `qa` -> `reviewer` est le contrat que la
  Slice 04 câblera.

Tous ces champs paraissent dans `SubagentRole.as_dict()`, donc dans `GET /api/subagent-roles` (ajout de
champs, rétrocompatible). Une valeur existante change aussi : `coder.tools` gagne `Agent` (cohérence avec
`can_spawn`). Le champ est seulement affiché ; aucun consommateur ne s'en sert pour restreindre les outils.

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
| `[code] [qa] Relire` (`qa` désactivé) | code | aucun (repli sur la consigne) | non | [qa] Relire |

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
| Activation de `research-lead` et `qa`, loadout `qa` -> `reviewer`, catalogue de Work Methods | Slice 04 |
| Outils d'orchestration du Mission Owner (spawn, délégation, relais) | Slice 05 |
| Règles du cerveau (rôles proposés, éphémère élargie) | Slice 07 |
| Rôle dans la scène, badge Mission Owner | Slice 08 |
| Onglet Settings > Sous-agents | Slice 10 |
