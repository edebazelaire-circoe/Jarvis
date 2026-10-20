# Work Methods

Une Work Method dit **comment bien travailler** pour un rôle : principes, réflexes de qualité, relations
utiles à envisager. Elle ne dit jamais **dans quel ordre** : pas d'étape, pas de séquence, pas de graphe.
Le Mission Owner reste seul juge de l'organisation pendant l'exécution (décisions D05 et D06 du handoff
`jarvis-organic-agent-orchestration`).

Code : `jarvis/domain/work_methods.py`. Tests : `tests/unit/test_work_methods.py`. Rôles qui les citent :
[subagent-roles.md](subagent-roles.md). Candidats appris et promotion : sections *Candidats* et *Promotion*.

## Contrat

`WorkMethod`, figée et bornée :

| Champ | Contrat |
| --- | --- |
| `method_id` | `[a-z][a-z0-9-]{1,47}`, stable |
| `version` | entier de 1 à 9999 ; `key` = `<method_id>@<version>` |
| `name`, `summary` | 80 et 300 caractères au plus, requis |
| `role_ids` | rôles auxquels la méthode s'applique (1 à 16 ids) |
| `principles` | 1 à 12 heuristiques uniques, 300 caractères chacune ; un ensemble, pas une liste d'étapes |
| `quality_checks` | 0 à 12 critères de qualité, mêmes bornes |
| `useful_relations` | relations à envisager quand elles servent, parmi `delegation`, `communication`, `adversary`, `qa`, `handoff` |
| `provenance` | `MethodProvenance` (ci-dessous) |

Le décodage (`from_payload`) est strict : toute clé inconnue est refusée, et une clé de plan (`steps`,
`sequence`, `order`, `graph`, `dag`, `nodes`, `edges`, `workflow`, `plan`) est refusée nommément, code
`work_method_is_not_a_plan`.

Le vocabulaire des relations (`USEFUL_RELATION_KINDS`) est importé de `agent_relations.RELATION_KINDS`,
sa source canonique ; le contrat des relations est [agent-relations.md](agent-relations.md).

## Versions et provenance

- Une version publiée ne se réécrit pas : `check_revision(previous, candidate)` accepte la même version au
  contenu identique, ou exactement la version suivante de la même méthode ; une même clé `id@version` au
  contenu différent est refusée (`work_method_version_conflict`). `latest_methods` rend la dernière version
  de chaque méthode.
- `MethodProvenance.origin` vaut `builtin`, `user` ou `promoted`. Une méthode `promoted` porte le candidat
  d'origine (`candidate_id`), qui l'a promue (`promoted_by`, jamais vide), quand (`promoted_at`, date avec
  fuseau) et des références de preuve bornées (`evidence_refs` : ids de mission, de relation QA,
  d'artefact ; jamais de raisonnement). La promotion est un acte explicite, jamais un effet de bord (D24).

## Choix par l'appelant

Depuis la Slice 05, l'agent qui lance un sous-agent peut nommer une méthode après le rôle
(`[general] [research] [quick-research] …`, [subagent-roles.md](subagent-roles.md) §2). Le hook l'appose si le
rôle la permet (`work_methods` du rôle), sinon il appose la méthode par défaut et consigne
`method_not_allowed` ; `agent.role_applied` dit la méthode réellement apposée.

## Rôles

`SubagentRole.work_methods` liste les méthodes permises et `default_work_method` celle proposée par
défaut. `check_role_methods(roles, methods)` refuse une référence à une méthode inconnue
(`work_method_unknown`) ou qui ne s'applique pas au rôle (`work_method_not_applicable`).

## Catalogue livré

`work_methods.BUILTIN_METHODS` (Slice 04), version 1, provenance `builtin`. `builtin_method(id)` rend une
méthode livrée ou `None`.

| `method_id` | Libellé | Nom dans le handoff | Rôles | Relations utiles |
| --- | --- | --- | --- | --- |
| `quick-research` | Recherche rapide | Quick Research | `research`, `web-research`, `research-lead` | — |
| `deep-research` | Recherche approfondie | Deep Research | `research-lead`, `research`, `web-research` | délégation, contrôle qualité |
| `comparative-research` | Recherche comparative | Comparative Research | `research-lead`, `web-research`, `research` | délégation, confrontation, contrôle qualité |
| `bug-investigation` | Enquête sur un bug | Bug Investigation | `coder`, `qa` | contrôle qualité |
| `result-review` | Revue d'un résultat | (QA) | `qa` | — |

Les principes sont des réflexes indépendants (« Reproduire le défaut avant de chercher sa cause »), jamais
numérotés ni enchaînés ; un test refuse une entrée qui commence par un numéro ou un connecteur d'ordre.

**Rattachement aux rôles.** Chaque rôle liste ses méthodes permises et, au plus, une méthode par défaut
([subagent-roles.md](subagent-roles.md), section 1). Seule la méthode par défaut est apposée par le hook sur
la consigne, rendue par `render_method` : `MÉTHODE DE TRAVAIL : <libellé> (<id>@<version>)`, le résumé, la
mention « des réflexes, pas des étapes », les principes, les critères de qualité et les relations à
envisager en français (`RELATION_LABELS`). Aujourd'hui `research-lead` -> `deep-research` et
`qa` -> `result-review` ; les autres rôles n'ont pas de défaut. Le journal `agent.role_applied` porte la
clé `work_method`.

**Lecture.** `GET /api/subagent-roles` (version 2) expose le catalogue livré (`work_methods[]`, charge utile
`to_payload`). `GET /api/work-methods` expose toutes les versions, livrées et promues (ci-dessous). Une
méthode ne s'édite pas : la seule écriture est la promotion explicite d'un candidat, par une personne.

## Candidats

Une approche adaptée en cours de mission qui **revient** avec de **bonnes issues** devient candidate (D24).
Code : `jarvis/domain/work_method_learning.py` (pur), `jarvis/core/work_method_learning.py`
(`WorkMethodLearningService`). Tests : `tests/unit/test_work_method_learning.py`,
`tests/unit/test_work_method_learning_service.py`, `tests/integration/test_work_method_promotion_e2e.py`.

**Preuves, et seulement celles-ci.** L'historique durable des missions ([mission-history.md](mission-history.md)),
lu par `mission_tree` sur les missions racines les plus récentes :

| Preuve | Source |
| --- | --- |
| l'usage d'une méthode | `AgentDeclarationFact.work_method` / `work_method_chosen` du **premier** Mission Owner de la mission (le hook y écrit la méthode qu'il appose, choisie ou par défaut) |
| l'approche | les natures des relations de la mission **closes et non retirées** (`delegation`, `communication`, `adversary`, `qa`, `handoff`), en ensemble |
| la qualité | la fin de la mission (`completed`, `failed`, `cancelled`) et le **dernier** verdict QA de la mission |

Jamais lus : Conversation Events, le raisonnement ou le texte d'un agent, Work State (vivant, effacé au
redémarrage), le journal du runtime. Une mission ouverte n'est pas un usage (`mission_open`) ; un propriétaire
sans déclaration est écarté (`declaration_missing`). Chaque lecture le compte (`scan`).

**Clé de répétition** (`ApproachSignature`) : rôle du Mission Owner, id de la méthode apposée (sans version ;
l'absence de méthode est une approche comme une autre), ensemble des natures employées dans l'ordre canonique
du vocabulaire. Une approche, pas une topologie : ni nombre d'agents, ni ordre, ni arête. L'id du candidat
(`wmc-<16 hex>`) dérive de la clé : stable d'une lecture à l'autre.

**Qualité d'un usage** (`rate_use`), sur preuve explicite seulement :

| Cas | Note | Raison |
| --- | --- | --- |
| mission `failed` / `cancelled` | mauvaise | `mission_failed` / `mission_cancelled` |
| dernier verdict QA `approved` | bonne | `qa_approved` |
| dernier verdict QA `rejected` / `correction_requested` | mauvaise | `qa_rejected` / `qa_correction_requested` |
| dernier verdict QA `findings` | non notée | `qa_findings` |
| terminée sans verdict QA | non notée | `no_quality_evidence` |

Le silence n'est jamais une approbation : une mission terminée sans relecture n'est pas bonne. Aucune
validation par l'utilisateur n'est retenue durablement aujourd'hui ; elle n'est donc pas une source. Une
approche sans QA ne devient jamais candidate.

**Seuils** (`CandidateThresholds`, `DEFAULT_THRESHOLDS`, rendus par la route) :

| Seuil | Valeur | Sens |
| --- | --- | --- |
| `min_uses` | 3 (refusé en dessous de 2) | missions closes de même clé ; une réussite isolée ne suffit jamais |
| `min_positive` | 2 | usages notés bons |
| `min_positive_share` | 0,75 | part des usages notés (bons + mauvais) qui sont bons |
| `scan_root_missions` | 64 | fenêtre : missions racines les plus récentes lues (`scan.truncated` au-delà) |

**Statuts** : `observing` (`not_enough_uses`, `not_enough_quality_evidence`), `insufficient_quality`
(`positive_share_below_threshold` : jamais proposée), `matches_method` (l'approche est déjà celle de la
méthode apposée : rien à apprendre), `candidate` (`thresholds_met`), `promoted` (une version promue cite ce
candidat). Chaque candidat porte ses comptes, ses `evidence_refs` (ids des missions bonnes et de leurs
relations QA approbatrices, 16 au plus) et un `draft` : la version suivante de la méthode de base, natures
employées ajoutées à `useful_relations`, principes recopiés. Sans méthode de base, pas de brouillon : la
personne écrit nom, résumé et principes.

Les candidats **ne sont pas persistés** : ils se recalculent à chaque lecture depuis l'historique, seule
source, et la promotion les recalcule avant d'écrire.

## Promotion

Un acte d'une personne, jamais d'un agent (`promoted_method`) :

- promoteur dans `HUMAN_PROMOTERS` (`user`), sinon `work_method_promoter_not_human` ;
- candidat au statut `candidate` au moment de la promotion, sinon `work_method_candidate_not_eligible` ;
- méthode sans provenance (posée par la promotion : `promoted`, candidat, `user`, date avec fuseau,
  `evidence_refs` du candidat) et sans clé de plan (`work_method_is_not_a_plan`) ; schéma `WorkMethod` complet ;
- révision optimiste : `expected_version` est la dernière version que la personne a vue (0 : aucune) ; une
  autre version courante donne `work_method_revision_conflict` ; la nouvelle version suit exactement la
  courante (`check_revision`), une méthode neuve commence à 1, une version déjà publiée donne
  `work_method_version_conflict` ;
- la méthode s'applique au rôle du candidat (`work_method_not_applicable`).

**Stockage** : table `work_method_versions` de `jarvis.sqlite3` (migration v11, schéma figé
`tests/schema/jarvis_state.v11.sql`, adaptateur `jarvis/adapters/sqlite_work_methods.py`). Une ligne par
version promue, `data` = `to_payload()`, colonnes recoupées à la lecture ; triggers : jamais réécrite ni
effacée ; clé primaire `(method_id, version)`. Les versions livrées restent dans le code. La table est le
journal des promotions ; le diagnostic dit `work_methods.promoted` (Core) et `work_methods.promotion_done`
(Control Center), les refus `work_methods.promotion_refused` / `work_methods.promotion_failed` avec leur code.

**Routes** :

| Méthode | Core (jeton) | Control Center | Réponse |
| --- | --- | --- | --- |
| GET | `/v1/work-methods` | `/api/work-methods` | `{"methods", "latest"}` |
| GET | `/v1/work-methods/candidates` | `/api/work-methods/candidates` | `{"candidates", "scan", "thresholds"}` |
| POST | `/v1/work-methods/promotions` | `/api/work-methods/promotions` | `{"method"}` ; 400 enveloppe, 403 promoteur, 404 candidat inconnu, 409 révision, 422 contrat |

Côté Control Center, le préfixe est gardé pour toutes ses méthodes (boucle locale, même origine) ; la
promotion exige de plus une page de même origine (`Origin` et `Sec-Fetch-Site: same-origin`, sinon
`promotion_requires_browser`), le corps est `{candidate_id, expected_version, method}` et le promoteur est
forcé à `user`. Aucun outil MCP ni outil du cerveau n'appelle ces routes. Limite dite : un processus local qui
forgerait ces en-têtes n'est pas arrêté, comme pour toute écriture du Control Center. Un délai dépassé
(10 s) peut cacher une promotion écrite : la relecture des candidats fait foi.

## État

- Fait (Slice 12) : preuve d'usage durable, candidats, seuils, promotion explicite, versions promues
  append-only, routes.
- Pas encore : le hook appose toujours la version **livrée** de la méthode (`builtin_method`) ; une version
  promue est publiée et lisible mais pas encore apposée sur les consignes, et une méthode neuve n'est citée
  par aucun rôle. Les apposer demande de les porter dans l'instantané lu par le hook
  (`subagent_roles_snapshot`) et de les rattacher aux rôles.
- Écran : Réglages > Sous-agents, fiche d'un rôle qui peut porter une mission, bloc « Approches observées »
  ([subagent-roles.md](subagent-roles.md) § 8). Une candidate sans méthode de base (brouillon absent) ne se
  promeut pas encore depuis l'écran : il faudrait y écrire nom, résumé et principes.
