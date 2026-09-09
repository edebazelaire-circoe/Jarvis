# Tâche 11 - Notes de passation

Slice de test uniquement : aucun fichier de `jarvis/` n'a été modifié. Les
scénarios demandés par `TASK.md` sont tous automatisés et déterministes.

## Ce qui est monté

`tests/integration/async_conversation_harness.py` assemble la pile réelle et
n'en double que trois points :

| Doublé | Pourquoi |
| --- | --- |
| `FakeRealtimeSession` | pas de fournisseur, et le test doit décider quand une sortie se termine |
| `FakeAudio` | pas de PortAudio, mais la comptabilité de lecture de production est conservée (le `played_ms` d'un barge-in est donc réel) |
| `ScriptedBrainBackend` | modèle fort volontairement lent : `run_turn` ne rend la main que sur ordre du test |

Tout le reste est du code de production : protocole local HTTP + websocket
`/v1/events`, `BrainOrchestrator`, `SpeechScheduler`, `PersistentVoiceRuntime`,
`RealtimeConversationBridge`.

Deux réglages de test, sans effet sur la production :
`SpeechScheduler.RECONNECT_DELAY_S` ramené à 50 ms, et un `web.AppRunner` dont
le délai d'extinction est de 50 ms au lieu de 60 s (sinon couper le protocole
avec un abonné connecté ferait durer une minute).

## Scénarios prouvés

| Étape `TASK.md` | Test |
| --- | --- |
| 4 - tâche longue : accusé rapide, progression, résultat | `test_a_long_task_acks_fast_then_speaks_progress_then_the_result` |
| 5 - interruption, révision d'intention, résultat à jour | `test_an_interruption_stops_the_output_and_the_result_follows_the_new_intent` |
| 6 - `Jarvis Mute` pendant le travail, réactivation | `test_jarvis_mute_leaves_the_work_in_core_and_speaks_nothing_stale` |
| 7 - bruit ambiant pendant LIVE | `test_ambient_noise_during_live_does_not_keep_the_session_alive` |
| 8 - coupure/reprise du flux d'évènements Core | `test_the_core_event_stream_reconnects_without_replaying_stale_progress` |
| garde-fou multi-tours | `test_three_turns_run_in_one_session_without_a_second_wake` |
| Décision 34 - aucun outil Core depuis la surface | `test_no_core_tool_is_executed_from_the_surface_in_continuous_mode` |
| Décision 32 - le cerveau au travail retient la session | `test_brain_work_in_flight_keeps_the_session_alive` |
| doublon d'évènement de parole | `test_a_republished_speech_is_never_spoken_twice` |

Les trois scénarios de concurrence (interruption, mute, coupure de flux) sont
rejoués trois fois via `@pytest.mark.parametrize`.

## Défaut de production trouvé et **non** corrigé ici

> **Arbitrage de l'orchestrateur (Décision 38, postérieur à ces notes).** Le cadrage
> ci-dessous a été vérifié contre le code et n'a été retenu qu'en partie. Le chemin de
> reprise **existe** : `BrainBackend.run_turn(turn, state, emit)` reçoit l'état public
> à chaque tour, donc le cerveau dispose du résultat manqué au tour suivant. Ce qui
> manquait vraiment est plus étroit — `submit()` repartait d'un état **vide** sur un
> cache froid alors que `rehydrate()` savait le dériver — et c'est corrigé. La route
> `/v1` et l'appel dans `activate()` ont été **refusés** : alimenter la surface
> Realtime avec des résultats qu'elle n'a pas le droit d'énoncer reconstruirait le
> danger supprimé par la Tâche 06 (Décision 34). Le silence au réveil est voulu.

**L'état public du cerveau n'est atteignable par aucune surface.**

`BrainOrchestrator.rehydrate()` (`jarvis/core/brain_service.py:212`) existe et
contient bien ce que l'utilisateur a manqué, mais :

- aucune route ne l'expose (`jarvis/protocol/server.py:58-68`) ;
- `LocalCoreClient` n'a pas de méthode correspondante ;
- `PersistentVoiceRuntime.activate()` ne lit que
  `GET /v1/conversations/{id}/context` (`jarvis/runtime/voice_v2.py:196`), qui
  rend `summary` + tours persistés.

Une parole jamais prononcée n'étant jamais persistée, le contexte que la
surface reçoit à la réactivation ne porte aucune trace d'un résultat produit
pendant un mute. La Décision 33 promet pourtant que « l'état public de la
tâche 10 est le chemin de reprise ».

`test_jarvis_mute_leaves_the_work_in_core_and_speaks_nothing_stale` constate
les deux moitiés : `core.brain.rehydrate()` contient le résultat, et le
contexte lu par la surface ne le contient pas. Le test documente le manque au
lieu de le masquer.

Correctif hors périmètre d'une tranche de test : il demande une route, une
méthode client, un appel dans `activate()` et surtout une décision sur ce que
la surface fait de cet état à la réactivation (le dire ? le tenir en contexte
silencieux ?). Voir la Décision 37 proposée, et prévoir une tâche dédiée avant
que le mode continu ne devienne le défaut.

## Ce que ces tests ne prouvent pas

- Rien d'acoustique. Que le son cesse dans les haut-parleurs, en combien de
  millisecondes, et si les haut-parleurs redéclenchent le VAD micro ouvert :
  seule la recette poste de travail (tâche 12) peut le dire. Ici `abort()` est
  appelé sur un double et le curseur est une comptabilité d'octets.
- Rien du fournisseur réel : le découpage de tours du VAD serveur d'OpenAI, la
  fidélité de `speak()` au texte du cerveau, la sémantique exacte de
  `conversation.item.truncate` restent à valider en direct.
- Rien de la latence réelle : le harnais n'exécute aucun modèle.
- L'accès calendrier/rappels du cerveau en mode continu n'est toujours **pas**
  vérifié (Décision 34, suivi requis) : ces tests prouvent seulement que la
  surface n'exécute plus rien elle-même.
