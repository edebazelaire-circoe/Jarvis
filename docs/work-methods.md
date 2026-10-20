# Work Methods

Une Work Method dit **comment bien travailler** pour un rôle : principes, réflexes de qualité, relations
utiles à envisager. Elle ne dit jamais **dans quel ordre** : pas d'étape, pas de séquence, pas de graphe.
Le Mission Owner reste seul juge de l'organisation pendant l'exécution (décisions D05 et D06 du handoff
`jarvis-organic-agent-orchestration`).

Code : `jarvis/domain/work_methods.py`. Tests : `tests/unit/test_work_methods.py`. Rôles qui les citent :
[subagent-roles.md](subagent-roles.md).

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

**Lecture.** `GET /api/subagent-roles` (version 2) expose le catalogue (`work_methods[]`, charge utile
`to_payload`). Les méthodes ne s'éditent pas : aucune voie d'écriture n'existe, et aucune promotion
silencieuse.

## État

Les candidats appris et leur promotion relèvent de la Slice 12 ; le choix d'une méthode autre que la
méthode par défaut par un Mission Owner, de la Slice 05.
