# Task07 — runtime, bruit et ownership device

Date : 2026-09-12. Réalisation autorisée après Task06 ; validation parent/release consignée séparément. Aucun appel fournisseur facturable ni test acoustique matériel. [Plan accepté](07-implementation-plan.md), [analyse du drain](device-playback-completion-plan.md), [contrat canonique](evidence07-canonical.md).

## Changement observable

Un candidat local non confirmé ne baisse plus le volume, en salle ouverte comme en Solo Owner. Il reste observable et la capture continue. Le VAD fournisseur confirme l'interruption acoustique ; en Solo Owner, seul le propriétaire confirmé l'autorise. Garde pré-upload, identification, rejeu et fail-closed sur perte du vérificateur sont conservés. L'interruption ne supprime pas le travail Core.

À la fin naturelle d'une réponse complète, le player appelle la vraie opération checked `RawOutputStream.stop(ignore_errors=False)` après les écritures et leur comptabilité. Le buffer device contrôlé dans les tests ne se vide que sur consommation explicite. Aucun COMPLETE n'est émis après le seul retour de write, un zéro de latence, ou une file Python vide. Après drain, sortie laissée arrêtée ; le prochain bloc admissible la démarre paresseusement sous le verrou natif.

`SoundDeviceRealtimeAudio.complete_output(manifest)` produit une preuve immuable sans texte. Identité session/output/response, instance audio, epochs et opération, parties réellement écrites, octets soumis/confirmés sont comparés au manifeste. La façade valide toutes les parties avant de joindre le transcript final ; les mots d'une partie manquante ou interrompue ne sont jamais extrapolés. Plusieurs appels identiques au drain partagent la même tâche et le même résultat. Stop/change d'epoch invalide cette preuve ; un ancien COMPLETE ne peut être réutilisé après interruption.

Le curseur inclut `content_index` et se compte depuis le début de la partie effectivement en lecture. Recevoir une partie future ne change pas ce curseur. L'adaptateur conserve séparément ce qu'il a reçu et cible la partie exacte pour truncate. L'identité complète de partie contient aussi `output_index`; le dernier item d'une réponse ne suffit pas à certifier l'ensemble.

## Native lifecycle et Stop

Les tâches open/write/drain/abort/close restent possédées après annulation de leur appelant. La fermeture attend l'owner d'ouverture avant d'utiliser les pointeurs. Ils sont retenus dès création, y compris après échec de start et échec de cleanup. La fermeture tente close même lorsque stop/abort échoue ; une fermeture échouée conserve son pointeur pour reprise. Stop/input applique le même principe. Aucun natif output ne chevauche un autre ; les opérations attendent `_output_lock`, tandis que les compteurs utilisent un verrou distinct non imbriqué.

Le redémarrage paresseux peut lui-même être lent : epochs, closing et admission sont revérifiés après son retour. Le token Task06 appelle `begin_write` immédiatement avant write, après start ; un préambule expiré pendant start ne peut donc pas envoyer son premier octet. Trois tests dédiés retiennent start pendant expiration, Stop ou close et vérifient zéro write.

`stop_output()` et `close()` rendent un booléen local : True après leur frontière établie, False si le nettoyage reste en attente. Le délai d'attente device par appel vaut250ms par défaut (`device_wait_s`, injectable en tests). Il ne garantit pas la durée du driver ni celle du shutdown complet, qui comprend aussi scheduler et fournisseur. Epoch et inadmissibilité changent avant l'attente. Une nouvelle écriture est refusée avant de créer un worker qui pourrait attendre le verrou bloqué, puis revérifiée sous verrou.

Un drain dépassant le délai retourne UNKNOWN, conserve son worker, interdit nouvelles écritures/réouverture et programme abort sérialisé après le retour natif. Une interruption/fermeture rend inéligible toute preuve tardive. Le micro peut continuer pendant le drain normal ; un Stop complet peut fermer l'entrée indépendante alors que l'output reste bloqué. `cleanup_pending` et `device_closed` expriment la différence entre attente et fermeture vérifiée.

Le bridge laisse passer les contrôles urgents même lorsque `_queued_audio == 0` et qu'une fence device reste en attente. Il invalide les sorties interrompues avant d'attendre le natif. La télémétrie distingue `local_output_stop_requested` de `local_output_stopped` ; aucune mesure d'arrêt physique n'est publiée comme acquise sur un résultat pending. Le rejeu owner n'attend pas indéfiniment un driver.

`PersistentVoiceRuntime` conserve `_pending_audio` indépendamment de `_pending_canonical_close`. Le ledger peut établir le fournisseur STOPPED alors que le contrôle global reste ERROR/cleanup pending : aucune projection idle/background, reprise du wakeword ou réactivation du périphérique n'est autorisée prématurément. Les appels mute concurrents rejoignent un owner unique. L'identité de l'appelant initial préserve le cas où le bridge demande lui-même mute, sans cancel/join de sa propre attente. Une activation pendant mute pending est refusée.

Le bridge ne laisse entrer le PCM identifié que pour une sortie déclarée encore vivante. Les tombstones terminales/interruption sont bornées128 ; oublier un ancien tombstone ne transforme pas un PCM sans sortie vivante en nouvelle sortie. L'adaptateur déduplique les déclarations response.created, y compris après éviction des détails ; sa saturation est explicite. L'audio tardif peut rester une observation canonique contradictoire mais n'atteint pas le périphérique.

## Seuils et replay bruit

Pas de tuning VAD intuitif dans cette tranche. Valeurs conservées : candidat800ms ; détecteur sur trames10ms,12 positives sur40 et6 consécutives, réfractaire50trames. Les options semantic/server VAD existantes restent propres à l'adaptateur, sans nouveau défaut ni promesse de latence sémantique. Le délai natif250ms borne l'attente applicative, pas la reconnaissance owner.

Le test synthétique représente63 candidats non confirmés (7 de classe bus/bruit ambiant et56 autres), sans prétendre utiliser l'enregistrement source. Résultat mesuré :63 événements candidat,63 rejets,0 changement de gain et0 cancellation. L'ancien code appliquait une baisse à chaque candidat ; le changement réduit cet effet audible à zéro sans prétendre réduire le nombre de détections locales lui-même. Les tests owner existants vérifient toujours l'interruption à confirmation et ses timestamps de capture. Une distribution acoustique avant/après exige un enregistrement/smoke matériel distinct.

## Observabilité vérifiée

Canal existant RuntimeJournal, lecture par `read_jsonl_tail`, sans système de logs parallèle ni son/transcript/biométrie ajouté.

| Événement / code | Niveau et sens |
|---|---|
| `voice.barge_in_pending`, `voice.barge_in_rejected`, `voice.barge_in` | Info, candidat sans modulation, rejet ou interruption ; `device_stopped` distingue confirmation et demande. |
| `audio.drain_requested`, `audio.drain_result` | Info demandé/complété/périmé/unknown ; résultat failed à error. Opération/output/epochs, parties, octets et durée native. |
| `audio.native_failed` / `audio_native_failed` | Error, opération native échouée ; type d'exception seulement. Aucun texte d'exception device. |
| `audio.cleanup_pending` / `audio_device_pending` | Warning, échéance applicative dépassée, worker toujours possédé. |
| `audio.output_stopped`, `audio.device_closed` | Info, frontière locale effectivement atteinte ; une branche skipped ne certifie pas un arrêt. |
| `audio.output_rejected` / `audio_output_not_live` | Info, PCM sans déclaration vivante écarté avant playout. |
| `voice.device_cleanup_pending` / `voice_device_cleanup_pending` | Warning, contrôle global non finalisé ; aucune réactivation. |
| `voice.device_cleanup_failed` / `voice_device_cleanup_failed` | Error, pointeur conservé, reprise du close nécessaire. |

Les tests avec vrais fichiers journal vérifient la fin naturelle, l'absence de COMPLETE tardif, le code des échecs natifs et l'ordre pending → fermeture device → background. Aucun probe temporaire ; le flux de test à buffer contrôlé est permanent sous `tests/fakes/audio_device.py`.

## Validation ciblée

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_device_playback_completion.py tests/unit/test_realtime_audio_lifecycle.py tests/unit/test_v2_playback_cursor.py tests/unit/test_v2_barge_in.py tests/unit/test_voice_duplex.py tests/unit/test_owner_barge_in.py tests/unit/test_owner_input_gate.py tests/unit/test_owner_replay.py tests/unit/test_solo_owner_acceptance.py tests/unit/test_v2_voice_toggle.py tests/integration/test_voice_production_composition.py tests/integration/test_voice_device_control_plane.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

Premier sous-gate runtime/device/composition :237 passed en7.08s. Le premier gate étendu trouve335 pass et1 assertion historique attendant le duck `[0.3]` dans le rollback open_room. Cette assertion compare désormais les deux chemins à `[]` ; les doubles de flux du test continuous-live acceptent les signatures checked sans retirer leurs assertions write/abort/close exclusifs. La première release parent a trouvé2197 pass,5 échecs et4 skips : les autres attentes héritées output_started sont corrigées par l'agent canonique. Aucun échec n'est masqué par un skip.

Après ces corrections et les tests lazy-start, gate ciblé final runtime : **64 passed en3.50s**, warnings as errors :

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_device_playback_completion.py tests/unit/test_solo_owner_acceptance.py tests/unit/test_v2_continuous_live.py tests/integration/test_voice_device_control_plane.py tests/integration/test_voice_production_composition.py -q -W error -o asyncio_default_fixture_loop_scope=function
```

Le fichier device contient25 tests. Les mini-reproductions indépendantes du parent confirment aussi : un seul drain pour deux appelants, aucune réutilisation COMPLETE après Stop, mute concurrent sans idle anticipé, reprise de failed-open/failed-close et absence de chevauchement Stop pendant start. La release complète finale appartient au gate parent ; son résultat est consigné dans le suivi de Task07.

Les tests de composition utilisent la vraie factory app, runtime, façade, adaptateurs et Core HTTP ; seuls websocket, wake et périphériques sont contrôlés. Ils prouvent aussi le cas sans manifeste : aucune confirmation inventée. Le fichier QA indépendant `test_voice_device_control_plane.py` exerce entrée/urgent pendant drain, Stop device pending et provider close concurrent sur la chaîne réelle.

## Limites

Gate parent final : **2205 passed,4 skipped en252.11s**, `scripts/verify_release.py` entièrement vert. Les cinq fixtures historiques du premier run ont été corrigées ; le contrôle final couvre aussi l'expiration/Stop/close pendant un lazy start lent. Slice07 acceptée ; rapport détaillé dans [review-07.md](review-07.md).

Un driver définitivement bloqué reste non annulable sans danger et peut retarder la sortie de l'interpréteur. L'application conserve ownership et incertitude ; elle ne tue pas le thread ni ne réouvre le même périphérique. La preuve est une fin de buffer à la frontière API device, pas une preuve de perception humaine ni un alignement temporel des mots. GPT-Live n'obtient aucune finalité par silence. Mesures acoustiques, comparaison de modèles et facturation restent hors de ce gate contrôlé.
