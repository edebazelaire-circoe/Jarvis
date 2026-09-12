# Slice 08 — revue et correction de livraison non confirmée

Date : 2026-09-12. Périmètre : `SpeechScheduler` et ses tests unitaires.

## Défaut reproduit avant correction

`_await_output()` débloquait la file après un délai si ni le fournisseur ni
la lecture locale ne possédaient encore la sortie. `_ActiveSpeech.status`
restait vide ; `_speak()` traitait cette absence de statut comme un succès.
Une réponse refusée sans audio, ou une fin de réponse perdue, pouvait donc
produire `voice.speech.completed` et un tour assistant complet jamais confirmé.

Reproduction autonome avec les doubles existants : `speak()` rend un identifiant,
aucun événement audio/de fin ne revient, l'adaptateur devient inactif et le
délai est réduit à 20 ms. L'ancienne version persiste le texte complet.

Avant modification de production :

```powershell
./.venv/Scripts/python.exe -m pytest -q tests/unit/test_v2_speech_scheduler.py -k 'unconfirmed_speech or missing_completion_keeps' -W error
```

Résultat : **3 failed, 2 passed, 28 deselected**. Les trois échecs constatent
exactement la persistance indue (`assert core.turns == []`). Variantes : aucune
réponse créée, fin perdue après premier audio, événement de fin sans statut.

## Modification

- `jarvis/runtime/speech_scheduler.py` : état initial et statut absent normalisés
  à `unknown`; seule une fin `completed` autorise la persistance complète.
  L'inactivité débloque toujours la file. Une sortie encore active côté fournisseur
  ou lecture locale continue d'être attendue. L'interruption partiellement entendue
  conserve son chemin de persistance avec `delivery=partial`.
- `tests/unit/test_v2_speech_scheduler.py` : cinq cas de régression paramétrés.
  Ils vérifient l'absence de faux historique, la poursuite de la file, l'isolement
  d'une ancienne fin tardive, la persistance de la réponse suivante réellement
  confirmée et les deux sources de lecture encore active.

Aucun nouveau canal, fallback, backend ou dépendance. Aucune modification de
PortAudio, aucun appel fournisseur réel, aucun commit Git.

## Contrat d'observabilité et de test

Décision 27 du handoff : utiliser `RuntimeJournal`, support officiel du dépôt,
plutôt qu'un `observability.cli`/LogBroker absent de ce projet.

- Fonction : livraison vocale ; canaux existants `voice.speech.*`.
- Corrélation : `conversation_id`, `speech_id`, `correlation_id`, `work_id`,
  `output_id` dans les données structurées existantes.
- Normal : `queued` puis `started` puis `completed` uniquement après une fin
  explicitement confirmée. La réponse suivante peut continuer normalement.
- Fin inconnue après délai : `voice.speech.output_stalled` niveau warning,
  code stable `speech_output_stalled`, `still_active=false`; puis
  `voice.speech.interrupted` niveau warning, `status=unknown`. Aucun
  `voice.speech.completed` ni tour assistant complet pour cette sortie.
- Lecture encore active : `output_stalled`, `still_active=true`, puis attente ;
  aucun abandon ni nouvelle phrase concurrente.
- Validation : assertions sur les événements structurés capturés par
  `RecordingJournal` dans les régressions. Aucun journal de session utilisateur
  n'a été présenté comme preuve d'une exécution réelle. Aucune sonde temporaire.

## Résultats après correction

Toutes commandes avec `./.venv/Scripts/python.exe -m pytest -q ... -W error` :

| Périmètre | Résultat |
| --- | --- |
| `tests/unit/test_v2_speech_scheduler.py` | 33 passed |
| `tests/unit/test_v2_continuous_live.py` | 18 passed |
| `tests/unit/test_surface_reflex_policy.py tests/integration/test_v2_async_conversation.py` | 40 passed |
| `tests/unit/test_v2_barge_in.py` | 26 assertions passent ; processus exit 1 à la collecte finale, SQLite non fermée |

Premier lancement regroupé des quatre derniers fichiers : 83 passed, 1 failed,
le warning SQLite étant collecté pendant un test continuous. Les relances isolées
attribuent cette fuite au fichier barge-in : son test utilisant
`SQLiteStateRepository` à la ligne 827 ne ferme pas le dépôt. Cette fixture ne
relève pas des fichiers autorisés pour la correction 08 ; transmise à
l'orchestrateur. Le gate regroupé n'est donc **pas déclaré vert**.

`git diff --check` : aucun défaut d'espacement ; avertissement Git habituel
de conversion LF vers CRLF seulement.

## Limites et prochain pas

Un statut `completed` conserve le sens du contrat existant de fin de lecture
relayée par le bridge ; cette tranche n'établit aucune mesure acoustique réelle.
Une livraison inconnue peut avoir été entendue partiellement : sans curseur fiable,
on ne fabrique pas une longueur ou une livraison complète.

Prochain pas : revue indépendante par l'orchestrateur, correction de la fermeture
SQLite dans la tranche de validation concernée, puis reprise de la slice 09.
