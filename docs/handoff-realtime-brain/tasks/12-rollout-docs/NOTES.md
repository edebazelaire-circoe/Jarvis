# Tâche 12a - Notes de passation

Périmètre exécuté : étapes 2, 3 et 4 du `TASK.md` — télémétrie de latence,
portes de déploiement et retour arrière, fumée fournisseur opt-in. Les étapes 6
à 9 (recette poste de travail, documentation du dépôt, rapport final) ne sont
**pas** faites : elles appartiennent à la tranche 12b.

## Les six mesures

`docs/04-testing-and-quality.md`, section « Latency telemetry ». Chaque mesure
porte `measure` et `elapsed_ms` dans `data`, ce qui les rend toutes trouvables
d'un même filtre. Le vocabulaire partagé est dans `jarvis/core/latency.py`.

| # | Mesure | Évènement | Clé de jointure | Origine |
| --- | --- | --- | --- | --- |
| 1 | `speech_started -> surface_first_audio` | `voice.latency.surface_first_audio` | `segment_id` (+ `speech_id` si le son vient du cerveau) | tâche 12a |
| 2 | `transcript_completed -> brain_turn_accepted` | `voice.latency.brain_turn_accepted` | `correlation_id` (+ `segment_id`) | tâche 12a |
| 3 | `brain_speech_requested -> first_brain_audio` | `voice.latency.first_brain_audio` | `speech_id` | tâche 12a |
| 4 | `user_interrupt_detected -> local_output_stopped` | `voice.barge_in` (`stop_latency_ms`) | `speech_id` | **tranche 09c**, seul le nom `measure` a été ajouté |
| 5 | `brain_work_started -> first_public_progress` | `core.brain.latency.first_public_progress` | `work_id` | tâche 12a |
| 6 | `brain_work_started -> completed` | `core.brain.latency.work_completed` | `work_id` | tâche 12a |

Détails qui comptent :

- `LatencyTracker` fabrique lui-même son message à partir du seul nom de la
  mesure : un appelant ne peut pas y glisser de contenu. Les champs de `data`
  restent la responsabilité de l'appelant, et le test cherche le texte du
  scénario dans la sérialisation complète de chaque évènement.
- Les deux bornes d'une mesure sont toujours prises dans le **même** processus
  (horloge monotone). La mesure 3 démarre donc à la *réception* de
  `brain.speech.requested` par la voix, pas à son émission par Core : le
  transport Core → Voice n'y est pas compté.
- La mesure 6 n'est pas émise pour un travail en échec ou annulé : une panne
  n'est pas une durée d'exécution.
- Le bridge relaie à l'ordonnanceur le **premier** bloc audio de chaque sortie,
  et lui seul. C'est ce qui rend la mesure 3 possible sans ouvrir un second
  lecteur du flux fournisseur.

## Porte de la Décision 34

`CONTINUOUS_BRAIN_DEFAULT_BLOCKERS` dans `jarvis/v2_config.py` est l'interrupteur.
`default_voice_arch()` rend `legacy` tant que la liste n'est pas vide, et c'est
le seul endroit qui décide du défaut. Voir la Décision 39 proposée dans
`docs/01-decision-log.md`.

Les deux bloqueurs actuels sont réels : le cerveau n'a aujourd'hui que Drive
(`jarvis/runtime/drive_mcp.py`). Aucun accès calendrier ni rappels ne lui est
câblé — vérifié par recherche dans `jarvis/runtime/` et
`jarvis/adapters/control_center_brain.py`.

## Ce qui n'a pas été vérifié

- **Aucune recette matérielle.** Micro, haut-parleurs, casque, écho,
  retriggering du VAD, barge-in réel : rien n'a tourné. Les millisecondes
  mesurées par la télémétrie n'ont jamais été comparées à ce qu'entend une
  oreille.
- **Aucune exécution contre le vrai OpenAI.**
  `tests/integration/test_live_openai.py` a été étendu au chemin continu
  (session Realtime, catalogue vide, `speak()`, premier audio, `cancel_output`)
  mais reste sauté par défaut et n'a **pas** été lancé. Son résultat est « non
  vérifié », pas « réussi ».
- L'accès du cerveau au calendrier et aux rappels reste non vérifié : c'est le
  contenu même de la porte.

---

# Tâche 12b - Notes de passation

Périmètre exécuté : étapes 8 et 9 du `TASK.md` — documentation du dépôt et
rapport final. **Aucun fichier de `jarvis/` ni de `tests/` n'a été modifié.**

## Fichiers de documentation touchés

| Fichier | Langue | Ce qui a été fait |
| --- | --- | --- |
| `README.md` | anglais | nouvelle section « Voice architectures (v0.2 realtime path) » ; correction de la promesse de confidentialité |
| `docs/ARCHITECTURE.md` | anglais | nouvelle partie « Realtime + async brain architecture (v0.2 path) » : processus, deux architectures, frontière surface/cerveau, contrats, parole et interruption, télémétrie, limites assumées |
| `docs/OPERATIONS.md` | mixte, section neuve en français | « Deux architectures vocales », bascule et retour arrière, porte bloquante, échecs bruyants, où atterrit la télémétrie, ce qui n'est pas vérifié ; deux lignes ajoutées au tableau des variables ; paragraphe Diagnostics corrigé ; renvoi depuis « La boucle voix → Claude → voix » |
| `docs/SECURITY.md` | anglais | §10 réécrit : deux journaux, deux comportements |
| `docs/ACCEPTANCE_STATUS.md` | anglais | nouvelle partie v0.2 : ce qui a tourné, ce qui reste **UNVERIFIED**, et la recette poste de travail du mode continu |
| `docs/handoff-realtime-brain/FINAL-REPORT.md` | anglais | rapport final, tâches 00 à 12 |
| `docs/handoff-realtime-brain/docs/01-decision-log.md` | anglais | Décision 41 ajoutée, « proposed by Task 12b » |

## La divergence trouvée entre la doc et le code

`README.md`, `docs/SECURITY.md` §10 et le paragraphe Diagnostics de
`docs/OPERATIONS.md` annonçaient, comme **défaut de sécurité**, que le contenu
des transcriptions est expurgé des journaux tant que `log_content` reste faux.
C'est vrai de `jarvis/diagnostics/logger.py` (chemin V1), c'est faux de
`jarvis/runtime/journal.py` (chemin v0.2), qui n'a aucun interrupteur de contenu
et écrit `text[:300]`.

Conformément à la consigne, le **code n'a pas été corrigé** : la Décision 40 a
déjà tranché en faveur de la console de debug. Ce sont les trois documents qui
ont été mis en accord avec le code, et la Décision 41 enregistre l'arbitrage.

## Vérifications faites avant d'écrire

Chaque affirmation documentée a été relue dans le code : `default_voice_arch()`
et `CONTINUOUS_BRAIN_DEFAULT_BLOCKERS` (`v2_config.py`), les deux refus du mode
continu (`voice_v2.py`, `app.py`), le catalogue vide (`realtime_tools.tools_for`),
les règles de surface (`openai_realtime.CONTINUOUS_BRAIN_OPERATING_RULES`),
l'ordre du barge-in (`realtime_audio._barge_in`), les six mesures et leur puits
(`core/latency.py`, `runtime/journal.py`, `app.py`), les évènements `brain.*`
(`core/brain_service.py`, `core/v2_services.py`).

Nuance relevée et écrite telle quelle : le serveur MCP Drive n'est **pas**
enregistré par JARVIS pour l'agent CLI. La Décision 34 dit « Drive est déjà
exposé à l'agent CLI » ; c'est vrai seulement si l'opérateur a lancé
`claude mcp add jarvis-drive …` lui-même. La documentation le précise désormais.

## Tests

Lancés par cette tranche, sur le poste :

```
.\.venv\Scripts\python.exe -m pytest -q          -> 686 passed, 4 skipped, 0 failed
.\.venv\Scripts\python.exe scripts\verify_release.py -> Release verification passed.
```

## Ce qui reste non vérifié

Inchangé, et désormais écrit dans le README, dans OPERATIONS, dans
ACCEPTANCE_STATUS et dans le rapport final : aucune recette matérielle, aucun
appel au vrai OpenAI, aucun accès agenda/rappels du cerveau confirmé.
