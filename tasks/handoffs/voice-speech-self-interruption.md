# Voix — Jarvis se coupe tout seul (auto-interruptions non attribuées)

Statut : **en pause** (16/09/2026). Reprise prévue après amélioration de la qualité des transcripts vocaux.

## Problème

L'utilisateur constate que Jarvis coupe régulièrement sa propre parole, sans raison compréhensible. Le symptôme est jugé comme l'un des défauts les plus graves de la voix.

Dossier de tâche d'origine (Drive) : `jarvis-voice-turn-arbitration` —
https://drive.google.com/drive/folders/1tHTHcH34m3D4zXCs_JQsOP3jFLpxYh0B
(README, docs/, slices 00 à 06). Ce dossier reste la référence ; ce fichier résume l'état réel au 16/09.

## Déjà couvert par le code actuel

Ces points de la tâche d'origine ne sont plus à faire :

- **Identités stables** : `speech_id` / `output_id` sont présents dans toutes les traces `voice.speech.*`.
- **Barge-in ≠ annulation du travail Brain** : le scheduler arrête la parole, le Brain continue.
- **Callbacks tardifs** : `active.interrupted` est collant ; un `response_done completed` tardif ne réécrit pas une interruption (`jarvis/runtime/speech_scheduler.py:1433`). Voir aussi le commit `73e5281`.
- **Réducteur canonique** : `jarvis/core/voice_state.py` bloque déjà les transitions tardives vers `COMPLETE` après `CANCELLED`/`INTERRUPTED`.
- **Faux barge-in écho/bruit** (retours [7] et [11] du 11/09) : semblent maîtrisés par le gate duplex/owner. Le 16/09 : 35 `voice.barge_in_rejected`, 0 barge-in accepté.

`SpeechScheduler` est déjà l'arbitre de fait. **Ne pas créer de nouvelle classe d'arbitrage parallèle** (décision n° 4 du dossier d'origine).

## Ce qui reste réel

Source : `runtime/trace.jsonl`. Depuis le 12/09, 5 paroles se terminent en `voice.speech.interrupted` avec `status: cancelled`, `played_ms: 0` et `reason: delivery_not_complete`, **sans aucun `voice.barge_in` avant**.

### Cas 1 — le Brain remplace sa propre parole en cours (aucune entrée utilisateur)

16/09, 08:51:54 → 08:51:56 :

```
54.403  voice.speech.started           output b54c0627  « C'est noté. J'ai lancé un deuxième agent… »
55.780  agent.ask                      nouvelle réponse Brain « Bonjour ! Je suis là… »
55.802  presentation_decided           deferred / stale_source
55.819  voice.latency.provider_first_pcm  output b54c0627 (l'audio arrive)
56.018  voice.speech.interrupted       b54c0627, cancelled, played_ms 0, delivery_not_complete
56.021  voice.speech.dispatched        nouvelle sortie 53c38c1b
56.118  voice.state.diverged           voice_state_generated_divergence
```

### Cas 2 — un nouveau tour utilisateur arrive au moment du dispatch

14/09 à 14:45:07 et 16/09 à 08:23:25 (même schéma, aussi 14/09 à 14:55:06 et 14:55:08) :

```
speech.dispatched + voice.input_submitted (même milliseconde)
voice.transcript                         nouvelle phrase utilisateur
core.brain.replies_superseded / dependency_revoked
voice.reflex.decided                     speak / useful_content_ready
voice.response_silent                    cancelled, realtime_response_without_audio
voice.speech.interrupted                 cancelled, played_ms 0, delivery_not_complete
```

### Cause racine identifiée : la raison se perd

`_invalidate_presentation()` (`jarvis/runtime/speech_scheduler.py:1043`) connaît la vraie raison (`stale_source`, `dependency_revoked`, `superseded`, `ttl`) et annule la sortie. Ensuite, la finalisation (`speech_scheduler.py:1433`) enregistre toute sortie non complète comme `INTERRUPTED / delivery_not_complete`, **exactement comme un vrai barge-in**. Dans les traces, on ne peut donc pas distinguer « l'utilisateur m'a coupé » de « le Brain s'est remplacé lui-même ».

### Questions ouvertes

- **Décision produit (cas 1)** : une réponse Brain plus récente a-t-elle le droit de couper une parole dont l'audio arrive déjà ? Si oui, à quelles conditions ?
- **Cas 2** : qui annule réellement la réponse provider ? Le retrait par le scheduler, le Reflex qui démarre, ou les deux ? Ce n'est pas tracé.
- Ces deux cas expliquent-ils à eux seuls le ressenti utilisateur ? Seulement 5 sessions vocales depuis le 12/09 : l'échantillon est trop faible.

## Prérequis avant reprise

Obtenir des transcripts de meilleure qualité, où l'on voit ce qui a été **réellement entendu** et à quel moment Jarvis s'est coupé. Sans ça, on ne peut pas relier le ressenti aux événements de trace.

## Plan proposé à la reprise

1. **Reproduire** (Slice 01 du dossier d'origine) : un test déterministe par cas, à partir des séquences ci-dessus.
2. **Garder la raison jusqu'au bout** : le terminal `voice.speech.interrupted` doit conserver `stale_source` / `dependency_revoked` / `superseded` / `ttl`, et n'afficher un barge-in que si `active.interrupted` est vrai. Correctif ciblé dans `SpeechScheduler`, pas de nouveau module.
3. **Trancher la règle de remplacement** du cas 1 avec l'utilisateur, puis la tester.
4. **Tracer l'auteur de l'annulation provider** dans le cas 2.

## PR #7 rejetée (historique)

La PR https://github.com/edebazelaire-circoe/Jarvis/pull/7 (`feat/voice-turn-arbitration`) a été jugée non mergeable :

- Slices 00/01 sautées : pas d'audit, pas de reproduction, `LOG.md` vide.
- Nouveau `jarvis/domain/speech_arbitration.py` branché nulle part, qui doublonne `VoiceSpeechState` (`domain/voice_state.py`) et `SpeechCandidateStatus` (`domain/speech_presentation.py`).
- Raisons inventées (`reflex_preempted`, `brain_superseded` : 0 occurrence dans le runtime) ; les raisons réelles (`stale_source`, `dependency_revoked`, `ttl`) sont absentes.
- Modèle faux : `PLAYING → CANCELLED` interdit, donc un remplacement ou un passage en arrière-plan pendant la lecture n'est pas représentable. Il lève `ValueError` sur les callbacks tardifs, perd un `played_ms` plus récent et grossit sans limite.
- « Parole ≠ travail Brain » encodé comme une constante `False`, ce qui ne prouve rien.
- Tests jamais lancés localement ; son propre test `test_supersede_is_cancellation_not_user_interruption` échoue en CI.

**À récupérer** : le commit `00a65d2` (`numpy>=2.0,<3` dans l'extra `dev` de `pyproject.toml`). Sur `main`, la CI s'arrête au chargement des tests avec 14 erreurs, faute de numpy ; ce commit la débloque.
