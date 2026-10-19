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

## Rôles

`SubagentRole.work_methods` liste les méthodes permises et `default_work_method` celle proposée par
défaut. `check_role_methods(roles, methods)` refuse une référence à une méthode inconnue
(`work_method_unknown`) ou qui ne s'applique pas au rôle (`work_method_not_applicable`).

## État

Aucune méthode n'est encore livrée : le catalogue et son rattachement aux rôles relèvent de la Slice 04,
les candidats appris et leur promotion de la Slice 12.
