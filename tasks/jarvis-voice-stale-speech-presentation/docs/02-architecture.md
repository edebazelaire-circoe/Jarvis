# Architecture

## Acteurs (inchangés)

- **Core** (`jarvis/core/brain_service.py`) : vérité, intentions
  (`intent_id`, `intent_epoch`), `pending_replies`, émission des
  `SpeechRequest` (`_emit_speech`, `announce_notice`).
- **Bouche** (`jarvis/runtime/speech_scheduler.py`) : éligibilité, file,
  sélection, dispatch vers la surface, suivi des sorties.
- **Bridge** (`jarvis/runtime/realtime_audio.py`) : seul consommateur du flux
  fournisseur ; lecture, quiescence, barge-in.
- **Surface Live** (`jarvis/runtime/live_frontend_session.py`) : `speak` =
  `append_spoken_result` immédiat ; pas d'annulation d'une sortie déjà ajoutée ;
  `cancel_output` = muet jusqu'à la fin de l'incarnation.

## Cycle de vie d'une présentation (cible)

```
                 nouvelle intention (tour adressé / promu)
queued ──► eligible ──────────────────────────────► held_for_brain
   │          │                                        │      │
   │          ▼                                        │      ▼
   │       started ──► completed (fin constatée)       │   not_revalidated
   │          │         (Live : preuve locale)         │   (tour cerveau réussi
   │          └──► interrupted (barge-in)              │    sans réémission)
   │                                                   ▼
   └──► superseded / expired (TTL, supersedes_key)   revalidated_as <new speech_id>
```

- `held_for_brain` est un état **non éligible**, tracé
  (`presentation_decided`, raison `held_for_brain`).
- La réémission est une **nouvelle** `SpeechRequest` de l'intention courante
  (nouvel id, nouvelle chaîne) ; l'ancienne passe `superseded` avec la raison
  `revalidated_as`. Pas de « réanimation » d'un id ancien : `_attempted_ids`
  et `_seen_speech_ids` restent vrais.

## Contrat Core ↔ bouche à ajouter (Slice 04)

- Core suit **toute** parole non transitoire émise (clé `speech_id`), pas
  seulement celles qui ont un `work_id`.
- À l'activation d'une intention, Core publie les `speech_id` qu'il remet au
  cerveau (évènement dédié ou champ de révision d'intention — choix en Slice
  04, documenté dans `docs/05-event-contracts.md` du dépôt).
- En fin de tour du cerveau **réussi**, Core publie le verdict par `speech_id` :
  `revalidated_as` (id de la nouvelle parole) ou `not_revalidated`.
- Tour échoué / abandonné : aucun verdict ; les paroles restent retenues et
  sont remises au tour suivant (bornées par `MAX_BRAIN_PENDING_REPLIES`, les
  plus anciennes au-delà passent `not_revalidated` avec trace).
- Parole émise **après** l'activation pour une corrélation déjà dépassée
  (cerveau en retard sur l'ancien tour) : retenue d'office par la bouche, et
  ajoutée par Core aux `pending_replies` du prochain tour — jamais perdue en
  silence.

## Fin de parole Live (Slice 02)

- Le bridge sait quand l'audio d'une sortie arrive (premier bloc relayé avec
  `speech_id`/`output_id`) et quand le périphérique s'est tu
  (`confirm_live_output_quiescence`, `_note_live_output_quiescent`).
- Nouveau signal bridge → bouche, par sortie : « audio observé puis quiescence
  stable depuis `live_completion_grace_ms` » ⇒ `active.status = "completed"`,
  `active.done.set()`.
- Sortie dont aucun audio n'arrive dans un délai borné ⇒ libération avec
  statut `unconfirmed` (tracée, ni complétée ni interrompue).
- À investiguer en Slice 02 avant de coder : l'observation de lecture Core
  (`observe_playback(..., terminal=True)`, registre de lecture canonique) fournit
  peut-être déjà une preuve terminale par `output_id`. Si oui, la réutiliser
  plutôt que d'en créer une seconde.

## Relais spontanés (Slice 03)

`announce_notice(text, *, kind, supersedes_key, ttl_s, work_id)` : le
Control Center déclare le genre. L'accusé de calibration et l'analyse
partagent `supersedes_key = "calibration:<event_id>"`.
