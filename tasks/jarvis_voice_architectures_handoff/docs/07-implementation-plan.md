# Task07 — bruit, interruption et preuve device

Plan initial en lecture seule, 2026-09-12, accepté par le parent. L'implémentation a ensuite été explicitement autorisée après acceptation de Task06. Les sections ci-dessous conservent le plan de référence ; réalisation, commandes et limites sont consignées dans [preuves runtime/device](07-runtime-device-evidence.md) et [preuves canoniques](evidence07-canonical.md). Aucune mesure matérielle n'est revendiquée.

Références : [Task07](../tasks/07-vad-interruption-noise/TASK.md), [analyse du drain](device-playback-completion-plan.md), [cartographie](current-code-map.md), [état canonique](../../../docs/state-model.md). Les symboles cités décrivent le code après Task05 ; relire les modifications Task06 avant d'éditer les points partagés.

## Responsabilités et minimum proposé

| Fichiers | Responsabilité Task07 |
|---|---|
| `jarvis/runtime/realtime_audio.py::SoundDeviceRealtimeAudio` | Écriture/drain/abort/start/close natifs sérialisés, jeton immuable de preuve, worker conservé, état output indisponible/nettoyage en attente. |
| `jarvis/runtime/realtime_audio.py::RealtimeConversationBridge` | Candidat/confirmation, fence de drain dans `_play_out`, routage urgent, invalidation avant attente, publication de preuve et libération ordonnée du scheduler. |
| `jarvis/runtime/voice_v2.py::PersistentVoiceRuntime` | Conserver ownership audio au-delà de l'annulation du bridge ; exposer nettoyage pending et interdire la recréation du périphérique tant que l'ancien worker le possède. |
| `jarvis/runtime/realtime_frontend_session.py` | Joindre preuve locale et identité canonique, transmettre via le dispatcher existant ; aucune seconde lecture provider ni écriture d'historique. |
| `jarvis/adapters/openai_realtime.py`, `jarvis/adapters/openai_realtime_frontend.py` | Préserver les parties audio/transcript et leur clôture ; paramètres VAD et finalité provider normalisés ici. |
| `jarvis/domain/voice_events.py`, `jarvis/domain/voice_frontend.py`, codec associé | Extension neutre étroite uniquement si nécessaire à l'identité des parties/provenance de preuve ; aucun objet SDK ni PCM dans l'ingress Core. Forme exacte à arrêter pendant l'implémentation. |
| `jarvis/audio/duplex.py`, propriétaire dans `jarvis/audio/owner_verifier.py` et `jarvis/domain/speaker.py` | Réutiliser détecteur, garde, snapshots owner et replay ; ne pas construire un second système de reconnaissance. Modifier les seuils seulement si les mesures le justifient. |
| `jarvis/core/voice_state.py`, `jarvis/core/voice_ledger.py` | Conserver le réducteur et l'unique projection heard ; ajustements limités au contrat de preuve si nécessaires. Aucun texte intended/generated promu implicitement. |
| `docs/05-reflex-optimization.md` du handoff, documentation d'état/feature | Seuils retenus, dépendance owner, mesures, preuves et limites finales. |

## 1. Candidat bruit sans effet audible

Dans `_on_near_end`, conserver capture/pré-roll et minuterie, mais supprimer le duck immédiat en salle ouverte. Un candidat expire ou devient interruption confirmée ; seul le second état déclenche `_barge_in`. Ne pas retarder la capture pour diminuer artificiellement les détections.

Réutiliser les règles Solo Owner : propriétaire confirmé coupe immédiatement, provider VAD consultatif, non-owner sans baisse/coupure, vérificateur perdu ferme l'admission avant upload. Aucun nouveau délai après confirmation owner. Préserver `_on_owner_state`, `_hold_for_candidate`, la garde pré-upload et le rejeu. Une attente de nettoyage device ne doit pas immobiliser indéfiniment l'event loop ni faire perdre le début capturé du propriétaire ; tracer les éventuelles limites de replay.

Point de départ mesurable : `barge_in_confirm_s=0.8` ; détecteur sur trames10ms, `min_frames=12`, `window_frames=40`, `min_run_frames=6`, réfractaire50 trames. Garder initialement ces valeurs puis comparer bruit et vraie interruption avant ajustement. Semantic VAD/eagerness restent derrière les capacités et paramètres existants de l'adaptateur ; ce n'est pas une preuve d'identité ni une raison d'autoriser une interruption provider automatique contraire au mode.

## 2. Drain réel dans le chemin normal

L'implémentation sounddevice installée documente que `RawOutputStream.stop(ignore_errors=False)` attend les buffers en attente via `Pa_StopStream` et expose les erreurs. C'est la frontière minimale proposée. Une file Python vide, le retour de `write`, `write_available`, la latence déclarée ou un délai écoulé ne suffisent pas.

Le worker `_play_out` appelle le drain à la fence terminale d'une génération `completed`, après le retour de toutes les écritures et de leur crédit d'octets. Ne pas effectuer cette attente dans `_handle_event`, consommateur des contrôles urgents. Aucune écriture suivante ne dépasse cette fence. Le chemin construit par la factory normale doit appeler le mécanisme : un helper inutilisé ne satisfait pas Task07.

Laisser la sortie arrêtée après drain réussi ; démarrage paresseux avant la prochaine écriture admissible, sous le même `_output_lock`. Garder le RawInputStream indépendant. Une erreur de redémarrage rend la sortie indisponible, sans effacer l'ancienne preuve ni prétendre que la nouvelle écriture a réussi.

Geler sur la boucle un jeton : instance audio/session, sortie locale/response, ensemble de parties, identité du flux, `_output_epoch`, `_playback_epoch`, octets écrits et identifiant d'opération. Vérifier identité/closing/epochs avant l'appel natif, puis revalider avant publication. `_output_lock` couvre chaque opération PortAudio de sortie ; `_cursor_lock` couvre les compteurs. Ne jamais imbriquer ces verrous. La fence couvre aussi l'intervalle entre retour natif de write et `_credit_written`.

## 3. Ownership natif et contrôle réactif

Une tâche/future explicitement conservée par l'objet audio/runtime possède le drain ; elle survit à l'annulation du player. Le timeout borne l'attente applicative et ne prétend pas interrompre PortAudio. Timeout, Stop ou fermeture invalident immédiatement l'éligibilité de la preuve. Ils exposent `UNKNOWN/cleanup_pending`, interdisent nouvelles écritures et réouverture du même périphérique, puis rejoignent une seule opération de nettoyage sérialisée. Stop répété rejoint cette opération, sans worker concurrent.

Trois risques concrets trouvés dans le code Task05 :

- `_dispatch` contourne la queue seulement si `_queued_audio > 0`. À la fence ce compteur peut déjà valoir zéro : maintenir le contournement urgent pendant drain pending, sinon `speech_started` attend la fin qu'il doit interrompre.
- `_barge_in` attend `stop_output()` avant de marquer toutes les sorties interrompues ; `_on_owner_state` attend ensuite sa fin avant le rejeu owner. Déplacer l'invalidation des epochs/sorties avant toute attente ; distinguer demande d'arrêt, attente bornée et arrêt physique confirmé. Le chemin de contrôle ne peut rester suspendu à un driver bloqué.
- `PersistentVoiceRuntime.mute` abandonne sa référence du bridge avant d'attendre sa fin. Il faut conserver explicitement l'owner audio pending, ne pas réactiver un nouveau flux prématurément et rejoindre le nettoyage lors des demandes suivantes. Auditer également qu'une annulation d'ouverture ne laisse pas un flux nouvellement ouvert sans propriétaire.

### Fournisseur fermé ne signifie pas périphérique arrêté

Le `FrontendState.STOPPED` du ledger peut légitimement établir la fermeture du frontend fournisseur alors que PortAudio reste dans une opération native possédée. Ne pas détourner ce statut pour lui faire signifier une preuve device, ni transformer une fermeture provider confirmée en événement provider inconnu uniquement pour représenter le matériel.

Le contrôle global doit composer les deux états : fournisseur fermé **et** device cleanup pending restent un arrêt global non finalisé. UI, traces et autorisation de réactivation montrent cette incertitude ; aucune annonce « haut-parleur arrêté » ou « ressources fermées » avant résolution. L'owner device doit vivre hors de l'entrée provider terminalisée/évictable du ledger. La réconciliation de fermeture provider Task05 reste distincte du nettoyage audio local. Une preuve tardive après invalidation ne transforme pas un tail annulé en heard.

Un driver durablement bloqué peut empêcher l'arrêt physique et retarder la sortie du processus. Aucun abort/close concurrent, thread kill ou nouvelle ouverture ne constitue une solution sûre. Le contrat est un contrôle applicatif réactif avec ownership observable, pas une garantie universelle de délai natif.

## 4. Toutes les parties du texte doivent être couvertes

Le code actuel conserve `content_index` dans l'objet privé OpenAI mais le perd dans `_output_payload` ; le frontend construit `transcript_id` avec session/output/item seulement et ne traduit pas `audio_done`. Un dernier item/cursor ne peut donc pas certifier toutes les parties d'une réponse.

Préserver un manifeste borné des parties audio/transcript, leur ordre, leur clôture et les octets reçus/écrits. Définir la plus petite extension neutre permettant cette jointure ; le détail provider reste dans l'adaptateur. Une fin complète Realtime peut fermer le manifeste. Une simple pause GPT-Live ne le peut pas.

La preuve device porte sur la sortie complète et son étendue ; le manifeste établit que chaque partie du texte correspond à de l'audio intégralement soumis puis drainé, sans écriture perdue/échouée et sans interruption. Transcript final tardif : joindre la preuve conservée de cette sortie exacte, jamais celle de la suivante. Conserver génération, intention et preuve séparées ; transmettre le texte confirmé cumulatif selon le contrat existant du réducteur. Partie manquante, zéro audio, réponse annulée/incomplète, flux ambigu ou epoch périmé restent partial/unknown. Ne jamais estimer des mots par proportion de durée.

## Contrat de tests

Créer un flux device de test avec `queued_frames`, `played_frames`, état actif/arrêté et horloge manuellement avancée. `write` enfile, `stop(ignore_errors=False)` attend la consommation avec Condition/Event, `abort` jette, `start` autorise les écritures. Détecter le chevauchement de toutes les opérations natives et échouer avant une entrée concurrente dangereuse. Délais finis et libération des workers en finally.

| Preuve | Chemins/tests à compléter |
|---|---|
| Replay synthétique des caractéristiques bruit : candidats non confirmés sans baisse/coupure ; comparaison avant/après des effets audibles et vraie interruption | `tests/unit/test_voice_duplex.py`, `test_v2_barge_in.py`. Ne pas présenter les caractéristiques71/63/7 comme un enregistrement réellement rejoué. |
| Owner confirmé/non-owner/snapshot ancien/vérificateur perdu/replay préservé | `test_owner_barge_in.py`, `test_owner_input_gate.py`, `test_owner_replay.py`, `test_solo_owner_acceptance.py`. |
| Vrai wrapper + factory/consumer canoniques : aucune COMPLETE après write seul, puis une confirmation/history après consommation device | `test_realtime_audio_lifecycle.py`, `test_realtime_frontend_pipeline.py`. Buffer100ms avec latence200ms, aucune preuve obtenue par zéro latence de fake. |
| Drain bloqué : capture/ticker/event urgent progressent, Stop retourne pending, aucune réouverture ni opération native concurrente | Lifecycle, voice toggle et pipeline ; observer aussi l'état global distinct du ledger provider STOPPED. |
| Annulation répétée/close/Stop avant ou pendant drain/changement d'epoch/session | Worker toujours possédé jusqu'au retour natif ; preuve périmée jamais publiée. |
| Erreur write/checked stop/start, timeout puis retour tardif | Erreur ou incertitude explicite ; pas de preuve COMPLETE, nettoyage sérialisé. |
| Plusieurs items et plusieurs parties par item, transcript tardif, doublon terminal, partie absente, audio tardif après interruption, zéro audio | Adaptateur frontend, pipeline canonique, réducteur/ledger si contrat étendu ; une seule projection heard. |
| Refus provider `no active response found` | Annulation/troncature idempotentes observables, état local conservé. |

Gate de régression : lifecycle, playback cursor, barge-in, owner, duplex, scheduler, voice toggle, frontend adapter/pipeline, codec/state/ledger, configuration et frontières d'import. Mettre à jour les fakes concernés par les nouvelles signatures natives explicitement, sans leur faire prétendre une consommation physique automatique.

## Contrat de logs et acceptation

Utiliser le `RuntimeJournal`/`DiagnosticSink` existant. États observables : candidat, confirmé, rejeté, demande d'annulation et résultat ; drain demandé, terminé, périmé, échoué, deadline dépassée et nettoyage résolu. Définir des codes stables pour les nouveaux chemins. Info pour transitions normales/périmées ; erreur device/timeout avec code et incertitude explicites ; conserver le traitement attendu des refus provider sans amplifier un résultat idempotent en panne fictive.

Données bornées : conversation/session/output/opération, epochs, nombre de parties, octets soumis/confirmés, durée native, cleanup pending et source d'autorité. Séparer onset→confirmation, confirmation→demande d'arrêt, confirmation→arrêt local réellement confirmé. Ne pas émettre `local_output_stopped` comme un fait quand seul Stop a été demandé. Aucun PCM, transcript dupliqué, secret ou biométrie.

Inspecter les vrais fichiers du journal via `read_jsonl_tail` sur une conversation normale intégrée et un drain bloqué suivi de Stop/cleanup. Produire les comptes de faux effets audibles avant/après et la distribution de latence de vraie interruption. Les fakes démontrent les règles d'ordre, de mémoire et d'ownership ; un smoke matériel distinct mesure drain du tail, délai de reprise et latence acoustique. Ne pas assimiler API device terminée à une preuve de perception humaine ou d'alignement temporel des mots.
