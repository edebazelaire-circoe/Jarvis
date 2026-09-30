# Niveaux de documentation

| Concept | Actuel | Requis | Écart |
|---|---:|---:|---|
| Fin de sortie (surface avec `response_done`) | 3 | 3 | préserver |
| Fin de sortie Live (preuve locale) | 1 | 3 | contrat bridge → bouche, marge, statut `unconfirmed`, tests |
| Éligibilité d'une parole d'intention passée | 3 (`carried_over`) | 3 | remplacer par `held_for_brain` + verdicts |
| Ordre de service (intention courante d'abord) | 1 (commentaire contradictoire) | 3 | règle explicite + test |
| `pending_replies` (toutes paroles non transitoires) | 2 (work_id seulement) | 3 | clé `speech_id`, remise sur échec |
| Verdict de revalidation Core → bouche | 0 | 3 | évènement dans `docs/05-event-contracts.md` |
| Genre des relais spontanés | 0 (toujours RESULT) | 3 | `kind`, `supersedes_key`, TTL obligatoires |
| Interruption = reprise d'autorité conversationnelle | 1 | 3 | gel de file unifié, tests réflexion/parole |

La Slice 01 fixe les comportements attendus en tests ; chaque Slice
d'implémentation remonte son concept au niveau requis (docstrings canoniques +
`docs/` du dépôt).
