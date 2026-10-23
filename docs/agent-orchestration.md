# Orchestration organique des sous-agents

Contrat du runtime d'orchestration du Mission Owner (handoff jarvis-organic-agent-orchestration, Slice 05).
Code : `jarvis/domain/agent_orchestration.py` (décisions pures), `jarvis/runtime/routing_hook.py` (le hook),
`jarvis/runtime/agent_declarations.py` (registre local), `jarvis/runtime/declaration_relay.py` (relais du
Control Center), `jarvis/protocol/mission_routes.py` (routes Core), `jarvis/core/mission_history.py`
(service). Voir aussi [subagent-roles.md](subagent-roles.md) (rôles, marqueurs),
[mission-history.md](mission-history.md) (historique durable), [work-methods.md](work-methods.md) et
[agent-relations.md](agent-relations.md).

## 1. Principe : organique, mécanique là où c'est possible

JARVIS ne lance aucun agent. Le cerveau et les sous-agents lancent leurs sous-agents avec l'outil `Agent`
du CLI Claude ; le seul point contraignant est le hook `PreToolUse`, qui voit chaque appel avant qu'il parte,
à toute profondeur, avec l'`agent_id` et l'`agent_type` de l'appelant quand l'appel est imbriqué.

- **Rien n'est planifié.** Aucune mission, aucune instance, aucun nœud n'est créé pour une étape envisagée :
  seul un appel `Agent` qui démarre réellement laisse une déclaration, et seule une déclaration jointe à une
  tâche démarrée devient une instance (D05, D15).
- **Une tâche triviale reste un agent.** Les outils sont enseignés comme une boîte à outils, avec le moment
  où ils servent, jamais comme une séquence ou un nombre d'agents (D05, D07).
- **Core est le propriétaire sémantique.** Le hook déclare ; Core enregistre et refuse (contrats de
  `missions`, `mission_history`). Le flux `stream-json` reste un diagnostic (D25).

## 2. Ce qu'un Mission Owner a sous la main

| Besoin | Outil | Qui le rend contraignant |
| --- | --- | --- |
| Lancer un agent d'un rôle explicite | `Agent`, description `[profil] [rôle] Libellé` | hook : méthode, loadout, charte, modèle |
| Confier une sous-mission que l'autre organise lui-même | `Agent`, `[profil] [rôle] [mission] Libellé` | hook (déclaration Mission Owner), Core (sous-mission) |
| Choisir la Work Method d'un agent | `Agent`, `[profil] [rôle] [<méthode>] Libellé` | hook (méthode permise au rôle, sinon défaut) |
| Réorienter un agent lancé | `SendMessage` (CLI) | autorité existante du parent sur ses enfants |
| Arrêter un agent lancé en fond | `TaskStop` (CLI) | autorité existante ; la fin part dans Work State (`cancelled`) |
| Relire le travail d'un enfant | son compte rendu, `TaskOutput` (CLI) | — |
| Inspecter une mission, sa trace, son état | `GET /api/missions/{id}` (Control Center), `GET /v1/missions/{id}` (Core) | lecture seule (§6) |
| Second regard, approches concurrentes, coordination explicite (Slice 06) | `mcp__jarvis-workspace__relation_start` / `relation_post` / `relation_read` / `relation_close` | Core (autorité, contrat), identité apposée par le hook ([agent-relations.md](agent-relations.md) §10) |
| Passer la mission à une instance neuve (Slice 06) | `relation_handoff`, puis `Agent` avec `[relais]` après le rôle | hook (billet réclamé, paquet apposé), Core (une transaction, avant la fin du prédécesseur) |

Slice 05 : aucun outil MCP nouveau pour le cerveau. Slice 06 : les outils de relation sont sur `jarvis-workspace`,
pour les sous-agents ; le test de parité exige qu'ils soient nommés dans la consigne du cerveau, ce que fait une
ligne de `BRAIN_WORKSPACE_PROMPT` (« à eux ; toi, relation_read seulement ») ; depuis la Slice 07,
`brain_rules()` dit au cerveau que ces gestes appartiennent aux Mission Owners : il les leur demande, ou
lance un Mission Owner, et ne fait que lire ([subagent-roles.md](subagent-roles.md) §9). Le bloc « RELATIONS ENTRE AGENTS (JARVIS) »
(`relation_runtime.relations_brief`) suit, en bloc distinct, la responsabilité de mission ; un relecteur QA reçoit
« RELATION QA (JARVIS) ». Le bloc
« RESPONSABILITÉ DE MISSION (JARVIS) » (`agent_orchestration.mission_brief`) est apposé par le hook, en
dernier, sur la consigne d'un Mission Owner seulement : propriété du résultat et de sa qualité (D22),
outils ci-dessus, « une tâche nette se fait seul », « rien de ce que vous ne faites qu'envisager ».
Il s'ouvre, après sa portée, par le paragraphe « RESTITUTION (JARVIS) » (Slice 11,
`delivery_quality.delivery_brief`) : surface jugée sur le résultat réel (`jarvis.table`, `jarvis.document`,
`jarvis.checklist`, réponse directe), affichage par `scene_create_object`, repli honnête ; la charte du
Mission Owner reçoit la note de compte rendu assortie ; contrat : [subagent-roles.md](subagent-roles.md) §5bis.

## 3. Décisions du hook

Pour chaque appel `Agent`/`Task` (`routing_hook.run`) :

0. **Tendance de délégation du cerveau** (`_delegation_guard`), avant tout : si le cerveau Core vaut `never`
   (`<runtime>/brain-config.json`, [brain-config.md](brain-config.md) § 3), un appel du cerveau (`agent_id`
   absent) est refusé `brain_delegation_never` ; un appel imbriqué passe. Fichier illisible : `standard`.
1. **Garde de lancement** (`decide_spawn_guard`) :
   - appel émis depuis le type restreint (`agent_type == "jarvis-no-spawn"`) : refus `caller_cannot_spawn` ;
   - borne de sûreté : au plus `MAX_SPAWNS_PER_WINDOW` (120) lancements par `SPAWN_WINDOW_S` (600 s), tous
     cerveaux du poste confondus, comptés sur les noms du registre local : refus `spawn_rate_cap` avec une
     raison lisible ;
   - rôle `can_spawn=False` et type `general-purpose` ou `claude` (toute casse, blancs de bord ignorés) ou
     absent : `subagent_type` réécrit en `jarvis-no-spawn` (`can_spawn_enforced`). `claude` est le type
     fourre-tout du CLI 2.1.304, aux mêmes outils (`*`) que `general-purpose` : le remplacer ne lui retire que
     `Agent`/`Task`. Tout autre type (`Explore`, `Plan`, `fork` — qui hérite du contexte de l'appelant, donc pas
     équivalent —, types de l'utilisateur) est laissé tel quel (`can_spawn_not_enforced`, consigné).
   **Activation** (reprise QA M1) : la garde ne s'arme que si l'environnement du hook porte
   `JARVIS_SPAWN_GUARD=jarvis-no-spawn@1`, posé par `claude_local` sur le CLI qu'il lance avec `--agents` et
   hérité par chaque hook (constaté sur le CLI 2.1.304, appel du cerveau et appel imbriqué). Aucun drapeau
   n'est plus ajouté à la commande du hook : un hook d'une version antérieure (argparse strict) sortait en 2
   sur `--spawn-guard`, et le CLI refusait alors **tout** appel `Agent`. Une autre valeur ou une autre version
   laisse la garde éteinte : un type inconnu du CLI ferait échouer l'appel.

   | Garanti | Non garanti (consigné `can_spawn_not_enforced`) |
   | --- | --- |
   | rôle `can_spawn=False` demandé en `general-purpose` ou `claude` (toute casse) ou sans type : part sous `jarvis-no-spawn`, sans `Agent`/`Task` | rôle `can_spawn=False` demandé sous un autre type (`fork`, `Explore`, `Plan`, type de l'utilisateur) : garde les outils de ce type |
   | appel `Agent` émis depuis `jarvis-no-spawn` : refusé (`caller_cannot_spawn`) | CLI lancé sans la variable (ancien lanceur) : rien n'est réécrit |
   | borne de débit pour tous les appels | rôle non déclaré : peut lancer, comme avant |
2. **Consigne** : charte consciente du rôle (`agent_charter.sign_brief(can_spawn=, constrained_output=)` : un
   rôle qui ne lance pas n'est plus invité à déléguer ; un rôle à sortie contrainte, l'Intervieweur, envoie le
   travail en plus au dossier de mission, jamais au compte rendu), playbook, méthode du rôle (choisie ou par défaut), manifeste du loadout,
   bloc de mission d'un Mission Owner.
3. **Mission** (`decide_mission`) : l'agent possède une mission si son rôle peut en porter une
   (`can_own_mission` : `coder`, `research-lead`) et que l'appel vient du cerveau (mission racine) ou porte
   `[mission]` (sous-mission). Id : `mis_<tool_use_id>`, stable au rejeu. Éphémère : jamais
   (`ephemeral_mission_owner` si `[mission]`). `[mission]` sur un rôle qui ne peut pas : consigné
   (`role_cannot_own_mission`), l'agent part comme membre.
4. **Déclaration** : pour un appel qui part (ni refusé par la garde ni par l'aiguillage), le fait
   `AgentDeclarationFact` v1 est déposé dans le registre local ; une panne de dépôt est consignée
   (`agent.declaration.failed`) et ne retient jamais l'appel. Journal : `agent.declared` (codes et ids :
   rôle, appelant, mission, méthode choisie ou refusée, garde, écrit ou non) ou `agent.spawn_refused`.

Le hook ne fait aucun appel réseau et ne lève jamais : `routing_hook.main` rattrape toute exception, sort en
0 sans rien écrire (le CLI garde la consigne d'origine) et consigne `agent.routing.failed`
(`routing_hook_crashed`). La sous-commande `jarvis routing-hook` tolère un argument inconnu
(`parse_known_args`) : un lanceur plus récent ne la fait jamais sortir en 2. La raison rendue au CLI porte la
note de la garde même quand la consigne n'a pas changé. Refus de la borne : il dit dans combien de secondes la
fenêtre libère une place.

### Le type d'agent restreint

`claude_local` passe au cerveau `--agents` (`agent_orchestration.agents_argument()`) avec un seul type,
`jarvis-no-spawn` : `disallowedTools: ["Agent", "Task"]`, tous les autres outils hérités (MCP compris), une
consigne courte. Constaté sur le CLI 2.1.304 : la réécriture de `subagent_type` par le hook est honorée
(`subagent_stats.by_type`), l'agent de ce type ne voit pas `Agent`, et il voit `mcp__jarvis-tools__*`.

## 4. Bornes de sûreté (ressources, pas doctrine)

| Borne | Valeur | Qui |
| --- | --- | --- |
| Profondeur de sous-agents sous le cerveau | 3 (l'agent de niveau 3 n'a plus `Agent`) | CLI, constaté le 2026-10-20 ; la charte le dit (`MAX_DELEGATION_DEPTH`) |
| Concurrence, budget | `subagent_stats.refused.{concurrency_limit,budget}` | CLI |
| Lancements par fenêtre | 120 / 600 s | hook (`spawn_rate_cap`) |
| Faits dans le registre local | 1 024 fichiers, élagués après 1 h | hook, Control Center |
| Profondeur de missions | 16 (`MAX_MISSION_DEPTH`) | Core |

Ce sont des bornes de ressources : aucune n'impose un minimum ni ne pousse à décomposer.

## 5. Registre des déclarations et relais

`<runtime>/agent-declarations/<ms>-<clé>.json` : un fichier par fait, écrit atomiquement (temporaire
puis renommage). La clé est le `tool_use_id` s'il ne contient que `[A-Za-z0-9_-]` (96 au plus), sinon
`h_<empreinte sha256>` : un id ne devient jamais un chemin ; le fait garde l'id d'origine. Un fichier illisible ou hors contrat est signalé (`missions.declaration_invalid`) et laissé
à l'élagage, jamais réparé.

Le relais du Control Center (`DeclarationRelay`, une tâche, sondage du registre toutes les secondes dans un
thread) :

- **jointure sur `tool_use_id`**, pas sur `work_key` : constaté en bac à sable, la clé de travail d'un agent de
  niveau 3 est son `task_id` (son appel `Agent` n'apparaît pas dans le flux ; seul `task_started` le montre,
  avec `parent_task_id`). `work_key == tool_use_id` ne vaut que quand l'appel est vu avant `task_started` ;
- la déclaration ne part qu'une fois la tâche **démarrée** (`task_id` connu) : clé définitive, et un appel
  refusé ne laisse aucune instance ;
- parent : la clé de travail du parent dans le suivi ; le suivi lit `parent_task_id` de `task_started` quand
  l'appel du parent n'est pas dans le flux (niveau 3) ;
- `role_for(task)` donne au `TrackerWorkObserver` le rôle du fait joint : `WorkObservation.role_id` (premier
  affirmé gagnant) ; `on_joined` renvoie les observations ;
- lots de 32 au plus vers `POST /v1/missions/declarations` ; Core injoignable : la file attend (256 au plus),
  `missions.relay_unavailable` puis `missions.relay_restored` ; lot refusé (400) : abandonné, consigné une
  fois par série ;
- **rejeu** : Core redémarré (nouveau `store_id`, lu dans chaque réponse et sondé par
  `GET /v1/missions/health` toutes les 30 s tant que des tâches jointes sont suivies) → les déclarations des
  tâches encore suivies repartent (`missions.relay_replayed`) : Core répond `duplicate` pour les durables et
  reconstitue les éphémères en attente. Control Center redémarré : le registre est relu (faits gardés 1 h).

## 6. Core : ingestion et lecture

`POST /v1/missions/declarations` (`mission_routes.py`) : enveloppe stricte (400 sinon) ; chaque élément est
décodé seul, et un élément hors contrat devient à sa place l'issue `refused` / `invalid_declaration` sans faire
perdre les autres (reprise QA). Pour chaque fait, `record_declaration(..., inherit_mission=True)` :

- un **Mission Owner** ouvre sa mission : objectif = libellé de la tâche (sinon « Mission sans libellé »),
  nature d'origine = profil, mission parente = celle de l'instance appelante
  (`MissionOpening(parent_from_caller=True)`), racine = celle du parent ;
- un **membre** hérite de la mission de son appelant ; sans appelant retenu (ou appelant sans mission), il
  n'a pas de mission.

Une mission se **clôt quand son propriétaire courant a fini ET que plus rien de son équipe ne vit** (reprise
QA M2) : aucun membre non terminal au regard de Work State, aucune sous-mission encore ouverte (réévaluée
d'abord). Sinon la clôture est différée (`mission_history.mission_close_deferred`) et réévaluée à chaque fin
observée et à chaque balayage, qui referme aussi une mission dont l'événement de fin a été perdu. L'issue suit
le propriétaire courant (`completed`, `failed`, `cancelled` ; `interrupted` → `cancelled`, mais seulement une
fois l'équipe finie). Un propriétaire dont Core ne sait rien (redémarrage, aucune fin vue, élagué sans fin
retenue) laisse la mission ouverte : rien n'est deviné. Après un relais explicite (`transfer_ownership`,
Slice 06), seule la fin du propriétaire **courant** compte. Journal : `mission_history.mission_closed`.

**Balayage tournant et missions orphelines.** Le balayage revoit au plus 64 missions ouvertes par passe, par un
curseur `(created_at, mission_id)` croissant qui repart au début une fois la fin atteinte : chaque mission
ouverte est revue au bout de ⌈ouvertes / 64⌉ passes. Une mission ouverte dont ni le propriétaire ni aucun membre
n'est connu de Work State, plus vieille que `ORPHAN_GRACE_S` (600 s) alors que Core tourne depuis plus que ce
délai (le relais a eu le temps de rejouer), et sans fin de propriétaire retenue, **n'est jamais close d'office** :
aucune issue n'est inventée. Sa vue porte `live_unknown: true` (dérivé, jamais persisté) et
`mission_history.mission_orphaned` est émis une fois.

Déclaration arrivée après une clôture : l'instance est **toujours** enregistrée (D18). `[mission]` sous une
mission close n'ouvre rien : instance retenue sans mission, diagnostic `mission_history.mission_parent_closed`
(code `mission_parent_closed`), et le rejeu est un doublon. Un membre tardif garde sa mission close, diagnostic
`mission_history.member_after_close`.

Lecture : `GET /v1/missions/health` (avec `store_id`), `GET /v1/missions/{mission_id}` (arbre, instances avec
statut vivant de Work State ou `null`), `GET /v1/missions/work/{work_source}/{work_external_id}`. Le Control Center les
relaie en lecture seule sous `/api/missions/health`, `/api/missions/{mission_id}`,
`/api/missions/work/{work_source}/{work_external_id}` (route à lecture protégée : objectifs et libellés viennent de
l'utilisateur ; 503 `core_unreachable` après 3 s, `not_configured` sans relais).

Contexte du cerveau : chaque entrée de travail retenue porte `mission_id` et `mission_owner` quand ils sont
connus (`MissionHistoryService.mission_ref`, sans E/S) ; `work_brief` écrit « mission : <id> (responsable) ».
Sans mission, l'entrée est identique à avant. La consigne système du cerveau n'est pas modifiée.

## 7. Rôle inconnu et rôle non déclaré

Un mot de tête qui n'est ni profil ni rôle annoncé n'est pas un rôle : il reste dans le libellé et la
déclaration porte `undeclared` (projection « générale » sûre). `unknown` reste réservé à un id de rôle de
forme valide que le registre ne connaît pas (fait d'un producteur plus récent, rôle retiré) : l'affichage
dégrade, rien n'est deviné ni réécrit. Aucun libellé n'est lu pour deviner un rôle.

## 8. Limites connues

- Un sous-agent lancé sous un type autre que `general-purpose` garde ses outils : `can_spawn` n'y est pas
  mécanique (`can_spawn_not_enforced` le dit). Les types natifs `Explore`/`Plan` n'ont pas `Agent`.
- Un cerveau lancé avant ce code (sans `--agents`) n'a pas `JARVIS_SPAWN_GUARD` : rien n'est réécrit tant
  qu'il n'est pas relancé. Le hook à jour dépose ses faits, mais seul un Control Center à jour les relaie, et
  seul un Core à jour (route `/v1/missions/declarations`, schéma v10) les enregistre : la mise en service
  demande un redémarrage complet, fait par l'utilisateur.
- Codex ne relaie aucune sous-tâche (`subtasks_supported` faux) : ni déclaration ni mission.
- Outils de relation (communication, QA, adversaire, relais) : faits en Slice 06 ([agent-relations.md](agent-relations.md)
  §10). Le transfert de propriété d'un relais est écrit à la déclaration du successeur, et un relais préparé
  diffère la clôture de la mission : la fin du prédécesseur ne la clôt pas. Un relais préparé vit en mémoire de
  Core : un redémarrage de Core entre la préparation et le lancement le perd (le successeur est retenu sans la
  propriété, dit à l'erreur).
