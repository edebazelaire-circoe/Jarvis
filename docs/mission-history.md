# Historique durable des missions

Page canonique de ce que Core retient, au-delà de la vie de Core Work State, des missions, des instances
d'agent et de leurs relations (handoff `jarvis-organic-agent-orchestration`, Slice 03 ; décisions D01, D08,
D16, D18, D25). Contrats réutilisés : [subagent-roles.md](subagent-roles.md) (rôles, missions, instances,
marqueurs de tête) et [agent-relations.md](agent-relations.md) (relations, tableaux, relais).

| Contrat | Code | Tests |
| --- | --- | --- |
| Fait de déclaration du hook, ouverture de mission (`MissionOpening`), issues, lecture jointe | `jarvis/domain/mission_history.py` | `tests/unit/test_mission_history_contracts.py` |
| Rôle explicite dans Work State | `jarvis/domain/work_state.py` (`role_id`) | idem, `test_work_state_contracts.py` |
| Port du magasin | `jarvis/ports/mission_history.py` | — |
| Tables v10 de `jarvis.sqlite3` | `jarvis/adapters/sqlite_state.py` (`_MIGRATIONS[10]`), `tests/schema/jarvis_state.v10.sql` | `test_mission_history_migration_v10.py`, `test_schema_migrations.py` |
| Adaptateur SQLite | `jarvis/adapters/sqlite_mission_history.py` | `test_mission_history_store.py` |
| Service Core | `jarvis/core/mission_history.py` (`MissionHistoryService`, câblé dans `v2_app.py`) | `test_mission_history_service.py`, `test_mission_history_rework.py` |

## 1. Deux vérités, deux natures

| | Core Work State | Historique des missions |
| --- | --- | --- |
| Dit | où en est l'exécution (`WorkStatus`, activité, compteurs) | qui a fait quoi pour quelle mission (rôle, mission, propriétaires, relations, fils, relais) |
| Durée | mémoire seule, 64 éléments, vidé au redémarrage de Core | `jarvis.sqlite3`, survit aux redémarrages |
| Identité | `(source, external_id)` | `instance_id`, joint à Work State par `(work_source, work_external_id)` |
| Statut d'exécution | **seule** vérité vivante (D16) | **aucune colonne de statut d'exécution** |

Le statut vivant d'une instance se lit dans Work State, jamais dans l'historique : `live_status` /
`InstanceView.work_status` rendent le statut du `WorkItem` de même identité, ou `None` quand Work State ne
connaît pas (ou plus) ce travail. `None` ne veut dire ni « fini » ni « échoué » : après un redémarrage ou un
élagage, l'historique ne sait pas et ne devine pas. `status` n'existe que pour le cycle de vie d'une
**mission** (`open -> completed | cancelled | failed`, l'objectif) et d'une **relation** (`open -> closed`),
jamais pour l'exécution d'un agent.

## 2. Source du rôle : le hook `PreToolUse`

Arbitrage D25 (audit de readiness §8 N5). Le rôle, l'éphémère, la mission et le parent annoncés viennent du
hook `PreToolUse`, avant le lancement, sous un contrat Core : `AgentDeclarationFact`, construit par
`fact_from_hook_event(event, declared_at=...)` sur la grammaire de `agent_markers`.

| Champ | Requis | Source |
| --- | --- | --- |
| `contract_version` | oui (`DECLARATION_CONTRACT_VERSION` = 1) | une autre version est refusée (`declaration_version`) |
| `tool_use_id` | oui | clé de jointure avec la tâche suivie ; sans elle : `declaration_unjoinable` |
| `declared_at` | oui | horloge du hook, avec fuseau |
| `role_id`, `role_status`, `role_marker` | oui, oui, non | `subagent_roles.resolve_role` : id canonique (`reviewer` -> `qa`, statut `alias`), `unknown` gardé tel quel avec son marqueur, `undeclared` sans marqueur |
| `ephemeral` | non (faux) | jeton `[éphémère]` de la description, jamais déduit d'une durée |
| `profile`, `label` | non | grammaire de tête ; libellé borné à 160 |
| `session_id`, `caller_agent_id` | non | événement du hook ; `caller_agent_id` n'existe que pour un appel imbriqué |
| `subagent_type`, `run_in_background` | non | `tool_input` ; une valeur hors contrat est laissée vide, pas corrigée |
| `mission_id`, `mission_owner` | non | annoncés par l'appelant (Slice 05) ; `mission_owner` exige `mission_id` |
| `handoff_id` | non | relais repris par ce successeur (Slice 06) ; absent quand vide |
| `work_method`, `work_method_chosen` | non | Slice 12 : la Work Method réellement apposée par le hook (`<id>@<version>`) et si l'appelant l'a nommée ; absents sans méthode. Preuve d'usage des candidats ([work-methods.md](work-methods.md) › *Candidats*) |

Interdits : `prompt`, trace, arguments, raisonnement. Le décodage est strict (`from_payload` refuse toute clé
inconnue). Le parsing `stream-json` du suivi des tâches (`agent_tasks.task_snapshot()["role"]`) reste un
affichage de diagnostic et n'alimente jamais l'historique ; les spans `subagent.*` de Conversation Events non
plus (audit N6) : ce sont des registres de diagnostic, pas des nœuds d'historique au sens de D08.

**Transport (câblé par la Slice 05, [agent-orchestration.md](agent-orchestration.md) §5-§6).** Le hook est
un processus court, sans réseau : il dépose le fait borné dans le registre local
`<runtime>/agent-declarations/` ; le relais du Control Center le rattache à la tâche suivie de même
`tool_use_id`, une fois démarrée, et le remet à Core (`POST /v1/missions/declarations`),
qui appelle `MissionHistoryService.record_declaration(fact, work_source=, work_external_id=,
parent_work_external_id=, mission=)`. `mission` est une `MissionOpening` (objectif, mission parente, dossier,
nature d'origine) : l'id de la mission est `fact.mission_id`, et **Core pose lui-même** le propriétaire (l'id
`ainst_<hex>` de l'instance qu'il crée pour cette déclaration), la racine (celle du parent) et la date
(`fact.declared_at`) — l'appelant ne peut pas connaître l'id d'une instance qui n'existe pas encore. Une
`Mission` complète est acceptée pour sa forme ; son propriétaire et sa racine sont remplacés de même. Refus :
déclaration qui n'est pas Mission Owner de cette mission (`ownership_invalid`, éphémère comprise : une
ouverture n'est jamais ignorée en silence), parent inconnu (`mission_parent_missing`), parent clos
(`mission_closed` : une mission close est gelée), objectif vide (`mission_invalid`). La racine d'une
sous-mission est celle de son parent, à toute profondeur. `work_external_id` est le `work_key` stable de la tâche (son premier
identifiant public), jamais l'`id` brut ni un libellé. **Constat du bac à sable (Slice 05) : ce n'est pas
toujours le `tool_use_id`.** Quand `task_started` précède l'appel (toujours au niveau 3, dont l'appel n'est pas
dans le flux), la clé est le `task_id` ; la jointure se fait donc sur le `tool_use_id` de la tâche suivie, et
c'est sa `work_key` qui part comme `work_external_id`. La route d'ingestion passe `inherit_mission=True` : un
membre hérite de la mission de son appelant retenu, une `MissionOpening(parent_from_caller=True)` prend pour
parente cette même mission. Le même transport porte le rôle jusqu'à `WorkObservation.role_id` (§5). Aucun appel bloquant vers
Core ne retarde le lancement.

`AGENT_DECLARED_KIND` (`agent.declared`) : événement de diagnostic d'une déclaration acceptée, avec
`role_id` canonique, `role_status`, `ephemeral`, `mission_id` (celle de l'instance, héritée comprise),
`mission_owner`, l'issue et l'instance. Le hook écrit un événement de même nom dans le journal du runtime
(fait déposé ou non, garde, méthode).

## 3. Ce qui est retenu (schéma v10)

Tables additives de `jarvis.sqlite3` (`_MIGRATIONS[10]`, sauvegarde automatique `jarvis.sqlite3.v9.bak`,
schéma figé `tests/schema/jarvis_state.v10.sql`). Comme les tables v3 à v8 : `data` est le `to_payload()`
canonique de la valeur du domaine, les autres colonnes en sont des copies relues et comparées à chaque
lecture (`MissionHistoryStoreError`, jamais réparé). Dates en clés UTC de largeur fixe.

| Table | Contenu | Garde-fous |
| --- | --- | --- |
| `missions` | `Mission` (objectif borné, parent, racine, propriétaire courant, cycle de vie) | identité, parent, racine et création figés ; une mission close est gelée (trigger) ; `closed_at` ssi close |
| `agent_instances` | `AgentInstance` + `ephemeral_lowered` + `declaration` (le fait, borné) | `UNIQUE(work_source, work_external_id)` ; **jamais éphémère** (`CHECK data.ephemeral = 0`) ; `data.role_id = role_id` ; rôle, identité, affectation, parent, création figés (trigger) |
| `mission_owners` | propriétaires successifs : le premier à l'ouverture, puis un par relais | append-only |
| `agent_relations` | `AgentRelation` (nature, mission, objet, clôture) | nature, mission, création figées ; une relation close est gelée |
| `agent_relation_participants` | participants et positions | fixés à la création |
| `agent_handoff_packets` | `HandoffPacket` du relais, prédécesseur, successeur | écrit avec sa relation, figé ; recoupé avec `agent_relations.data.handoff` |
| `agent_relation_messages` | `RelationMessage` | `seq` AUTOINCREMENT = ordre du fil (ordre d'acceptation) ; jamais réécrit |

Missions et propriétaires se référencent mutuellement : les deux clés étrangères sont `DEFERRABLE` et une
mission naît **avec** l'instance qui la possède, dans une transaction (`record_instance(..., mission=)` au port ; au service,
`record_declaration(..., mission=MissionOpening(...))`) ; il n'y a pas d'ouverture de mission isolée, puisque `Mission.owner_instance_id` est requis et que cette instance
nomme la mission. Plusieurs instances peuvent porter `mission_owner` pour une même mission (successeurs après
relais, N8 de la Slice 01) : seul `missions.owner_instance_id` nomme le propriétaire courant.

## 4. Règles d'écriture

- **Instances (D01).** Une même identité de travail enregistrée deux fois passe par
  `missions.reconcile_instance` : identique -> sans effet (`duplicate`), seul un libellé vide s'enrichit ;
  rôle, éphémère, mission, statut Mission Owner différents -> refus `immutable_field`. L'id déjà attribué fait
  foi. Le parent n'est pas déclaré : Core le résout une fois, par l'identité de travail du parent dans la
  même source (`parent_work_external_id`, c.-à-d. `WorkItem.parent_external_id`) ; un parent non retenu laisse
  l'instance sans parent durable. Mission inconnue -> `mission_unknown` ; parent absent ->
  `mission_parent_missing` ; chaîne plus profonde que 16 -> `mission_too_deep`.
- **Missions.** Sous-mission : parent retenu et ouvert (`mission_closed` sinon), même racine. Clôture une fois (`mission_closed` ensuite).
  Changement de propriétaire : `transfer_ownership(mission_id, successor, handoff_relation_id=)` exige une
  relation `handoff` de cette mission, non retirée, du propriétaire **courant** vers le successeur, lui-même
  Mission Owner de la mission (`ownership_invalid` sinon) ; la mission et la ligne `mission_owners` sont
  écrites ensemble.
- **Relations.** Dans une transaction : mission connue et ouverte, créateur connu,
  `check_relation_participants(relation, instances, missions=, relations=)` sur l'arbre de la mission, puis
  `check_handoff_chain` pour un relais ; relation, participants et paquet écrits ensemble. Une relation
  rejouée identique est sans effet ; un même id au contenu différent -> `relation_conflict`.
- **Messages.** `check_message` (relation ouverte, auteur et audience participants, réponse à un message
  antérieur du même fil, frontière de confidentialité) ; ordre du fil = ordre d'acceptation ; au plus
  `MAX_MESSAGES_PER_RELATION` (1 000) par relation, borne de stockage et non protocole (`relation_board_full`) ;
  rejeu identique sans effet, contenu différent -> `message_conflict`.
- **Relais (Slice 06).** `record_handoff(instance, declaration=, relation=, at=, summary=)` écrit en **une**
  transaction l'instance neuve du successeur, la relation `handoff` (paquet compris), le transfert
  (`mission_owners`) et la clôture `transferred` ; une instance déjà retenue est refusée
  (`handoff_successor_not_fresh`). Les écritures de l'adaptateur sont des fonctions de module
  (`_write_instance`, `_write_relation`, `_write_transfer`, `_write_close`) composées dans cette transaction.
- Une contrainte SQLite qui refuserait une écriture déjà validée par le domaine est un défaut :
  `mission_history_constraint`. Tout autre refus SQLite est `MissionHistoryUnavailable` (cause SQLite dans le
  message).

## 5. Work State : rôle explicite et lien `work_key`

`WorkObservation`, `WorkItem` et `OBSERVATION_WIRE_KEYS` portent `role_id` (id canonique ou `None`). Il est
posé par l'émetteur à partir du fait de déclaration (Slice 05), **jamais lu d'un libellé**. Le premier rôle
affirmé fait foi : une observation qui en annonce un autre est appliquée sans le réécrire et la contradiction
est rendue dans `WorkUpdate.conflicts` (`core.work.observation_conflict`), comme `work_id` ou `board_id`.
`BrainWorkEntry.role_id` le montre au cerveau (quelques octets dans le budget de 6 000 caractères) et
`work_brief` l'écrit « rôle : <id> ». Work State ne porte ni mission ni relation : ce sont des faits
d'historique, lus par jointure. Depuis la Slice 05, le relais du Control Center pose `role_id` (rôle du fait
joint, `undeclared` compris) et le contexte du cerveau joint la mission (`BrainWorkEntry.mission_id`,
`mission_owner`, absents sans mission) par `MissionHistoryService.mission_ref`, mémoire bornée sans E/S. Depuis la Slice 06, il joint aussi les relations connues de l'instance (`BrainWorkEntry.relations`, quatre lignes au plus, `relation_refs`, sans E/S ; [agent-relations.md](agent-relations.md) §10.6).

## 6. Éphémère (D08)

Aucune ligne durable n'est écrite pour une instance **tant qu'elle est éphémère** :

1. la déclaration éphémère attend en mémoire (au plus 256, la plus ancienne oubliée avec diagnostic) ;
2. Work State dit l'issue (abonnement tolérant à `core.work.updated`, plus un balayage contre l'instantané
   pour un événement perdu) :
   - réussite (`completed`) -> oubliée (`ephemeral_discarded`), et la clé est retenue (4 096 au plus, la plus
     ancienne oubliée avec un avertissement `mission_history.discarded_forgotten`, une fois) pour qu'un rejeu
     tardif de la déclaration ou de l'observation ne la ressuscite pas, même quand Work State l'a déjà élaguée ;
   - clôture d'un doublon fusionné (`cancelled` avec `error_class = merged`, `work_state.MERGED_CLOSURE`, envoyée
     sans drapeau par le relais du Control Center) -> traitée comme une réussite : ce n'est pas une fin du
     travail, l'éphémère est écartée (`ephemeral_discarded`) et sa clé retenue, jamais retenue en base
     (`missions.discarded_without_trace`, `retained_in_history(..., error_class)` ; reprise S8 QA) ;
   - échec, arrêt, interruption ou blocage -> le drapeau est rabaissé (`missions.retained_in_history`, même
     règle que `work_state.EPHEMERAL_WORK_STATUSES`), l'instance devient ordinaire et est retenue avec
     `ephemeral_lowered = 1` ; la déclaration d'origine (`ephemeral = true`) reste dans `declaration` ;
     `agent.declared` est émis (issue `ephemeral_retained`), quelle que soit la voie (déclaration ou
     observation) ;
3. une déclaration éphémère qui arrive après l'issue suit le statut vivant du moment.

Une éphémère ne possède pas de mission (`ephemeral_mission_owner`) et n'est jamais participante d'une
relation (elle n'est pas dans l'historique : `relation_participant_missing`). Un redémarrage de Core vide
l'attente : rien de durable n'avait été écrit, le rejeu du producteur la reconstitue.

## 7. Redémarrage, rejeu et réconciliation

- L'historique n'est pas rejoué : il est déjà durable. Work State repart vide (nouveau `store_id`) ; tant que
  le producteur n'a pas rejoué, `work_status` vaut `None`.
- Une déclaration rejouée est réconciliée (`duplicate`) ou refusée (`refused`, `immutable_field`) : le rejeu
  ou une observation tardive ne réécrit jamais un rôle (ni dans l'historique, ni dans Work State).
- L'historique ne contredit pas Work State : il ne porte aucun statut, et un `WorkItem.role_id` différent de
  celui de l'instance retenue est signalé (`mission_history.role_mismatch`, avertissement) sans rien réécrire
  d'un côté ni de l'autre.
- Le démarrage journalise `mission_history.ready` avec le nombre de lignes de chaque table, puis lance un
  balayage (`sweep`) aussitôt et toutes les `SWEEP_INTERVAL_S` (30 s), en plus de celui qui suit chaque
  `core.work.updated` ; un seul balayage à la fois ; un échec est signalé (`mission_history.sweep_failed`) et
  n'arrête pas la boucle.
- **Contrat de rejeu du producteur** : les éphémères en attente vivent en mémoire de Core et disparaissent à
  son redémarrage ; le relais du Control Center reconnaît le nouveau `store_id` et renvoie les déclarations
  des tâches encore suivies ; les durables répondent `duplicate`.
- **Clôture** : propriétaire **courant** terminé ET équipe terminée (aucun membre vivant dans Work State,
  aucune sous-mission ouverte) ; sinon différée et réévaluée à chaque fin et chaque balayage. Issue du
  propriétaire (`interrupted` → `cancelled`). Déclaration tardive : instance toujours retenue (D18), sans
  sous-mission sous une mission close (`mission_parent_closed`). Détail : [agent-orchestration.md](agent-orchestration.md)
  §6. `mission_history.mission_closed`, `…mission_close_deferred`, `…mission_close_failed`.

## 8. Fournisseur dégradé

| Panne | Comportement |
| --- | --- |
| SQLite refuse (verrou, E/S), lectures comprises | `MissionHistoryUnavailable` ; l'historique passe `degraded` (`health()`, diagnostic d'erreur `mission_history.degraded`, une fois par épisode) ; la déclaration rend `degraded` ; si même la lecture a échoué (panne totale : `find_instance`, ou
`get_mission` du parent d'une ouverture), c'est le fait brut (fait, identité de travail, parent, ouverture)
qui attend et que `sweep` rejoue intégralement ; sinon l'écriture prête attend (256 au plus, la plus ancienne perdue avec une erreur `mission_history.pending_dropped`) et
est rejouée au balayage suivant ; une écriture rejouée que le magasin refuse alors (contrat) est retirée avec
une erreur `mission_history.unsaved_refused` ; l'API d'écriture (Slices 05/06) lève, l'appelant voit le refus réel |
| Retour du magasin | premier succès : `mission_history.recovered` (durée, écritures échouées, restantes, comptées après le retrait de l'écriture rejouée). Le diagnostic nomme l'opération réelle (`record_instance`...) |
| Ligne illisible | `MissionHistoryStoreError`, signalée à l'erreur, jamais réparée |
| Work State indisponible ou vidé | l'historique reste lisible ; `work_status` = `None` |
| Journal indisponible | ignoré (même règle que `WorkStateStore`) |

Dans tous les cas, le travail vivant continue : rien ne remonte vers l'ingestion de Work State, et Core
démarre même si l'historique est refusé.

## 9. Ce qui reste à câbler

| Sujet | Où |
| --- | --- |
| Relations au runtime (communication, QA, adversaire, relais, délégation alignée) ; leurs résumés dans le contexte du cerveau | fait (Slice 06, [agent-relations.md](agent-relations.md) §10) |
| Projection dans la scène (rôles, relations, absence des éphémères terminées) depuis `mission_view` | fait (Slice 08, [scene-model.md](scene-model.md) › *Roles and agent relations*) |
| Lecture de l'historique dans l'UI (graphe, Settings) | Slices 09, 10 |

Câblés par la Slice 05 : hook source du fait, registre local, relais, route d'ingestion, `role_id` sur Work
State, mission dans le contexte du cerveau, `health()` exposé, balayage périodique, clôture des missions
([agent-orchestration.md](agent-orchestration.md)).

### Missions orphelines (note pour la Slice 08)

Après un redémarrage complet, une mission dont ni le propriétaire ni aucun membre n'est connu de Work State reste
`open` en base : rien n'est deviné ni clos d'office. `GET /v1/missions/{mission_id}` (et `/api/missions/...`)
porte par mission `live_unknown` (dérivé, jamais persisté : vrai après `ORPHAN_GRACE_S` = 600 s depuis le
démarrage de Core et la création de la mission), et `mission_history.mission_orphaned` est émis une fois. **La
Slice 08 (et toute UI) affiche ces missions « état inconnu », jamais « en cours ».** (Slice 08 : la scène ne
recopie pas l'état des missions ; la projection n'écrit jamais `exec_state` depuis l'historique, et l'UI lit
`live_unknown` dans cette route.) Le balayage tournant
(64 par passe, curseur croissant) revoit toute mission ouverte en un nombre borné de passes et clôt celle dont
la fin, perdue par le bus, est encore lisible dans Work State.

## 11. Routes

| Méthode | Route Core (jeton) | Control Center (lecture seule, sauf relations : Slice 06) | Réponse |
| --- | --- | --- | --- |
| POST | `/v1/missions/declarations` | — (relais seulement) | `{"store_id", "results": [{outcome, instance_id, code, message}]}` ; enveloppe stricte (400) ; un élément hors contrat = `refused` / `invalid_declaration` à sa place, les autres enregistrés |
| GET | `/v1/missions/health` | `/api/missions/health` | `HistoryHealth` + `store_id` |
| GET | `/v1/missions/{mission_id}` | `/api/missions/{mission_id}` | missions (chacune avec `live_unknown`), instances (statut vivant ou `null`), relations, propriétaires, `truncated` ; 404 `mission_not_found` |
| GET | `/v1/missions/work/{work_source}/{work_external_id}` | `/api/missions/work/{work_source}/{work_external_id}` | l'instance retenue ; 404 `mission_instance_not_found` |
| POST | `/v1/missions/relations` | `/api/missions/relations` (outils de relation, agentId résolus) | Slice 06 : `{"relation"}` ; 403 autorité, 409 contrat (message actionnable), 400 enveloppe |
| GET | `/v1/missions/relations/{relation_id}?after&limit` | `/api/missions/relations/{relation_id}` | la relation, `messages` (avec `seq`), `participants` (statut vivant) ; 404 `relation_unknown` |
| POST | `/v1/missions/relations/{relation_id}/messages` | idem | `{"seq", "message"}` |
| POST | `/v1/missions/relations/{relation_id}/close` | idem | `{"relation"}` |
| POST | `/v1/missions/handoffs` | `/api/missions/handoffs` (dépose aussi le billet du hook) | `{"handoff"}` : relais préparé, en mémoire de Core jusqu'au successeur |

Refus codés `{"error": {"code", "message"}}` côté Core (`mission_history_unavailable` 503,
`mission_history_failed` 500, `invalid_request` 400), journalisés `core.missions.route_failed` avec leur code ;
côté Control Center `{"ok": false, "code", "error"}`, `core_unreachable` 503 après 3 s, journalisé
`missions.read_failed`.

## 10. Mise en service

La migration v10 s'applique au démarrage de Core, après la sauvegarde `jarvis.sqlite3.v9.bak` : sur le
JARVIS vivant, elle demande un redémarrage de Core par l'utilisateur. Le code v9 refuse ensuite la base
(`state DB schema 10 is newer than supported 9`) ; retour arrière : restaurer `jarvis.sqlite3.v9.bak` (voir
[local-data.md](local-data.md)).
