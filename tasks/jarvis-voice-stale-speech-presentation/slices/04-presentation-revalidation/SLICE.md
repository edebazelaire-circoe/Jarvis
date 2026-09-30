# Slice 04 — Présentation revalidée : la vérité survit, la formulation attend le cerveau

## Goal

Après une nouvelle intention, aucune formulation rédigée avant elle ne démarre
d'elle-même ; le cerveau la reçoit, et seule une réémission sous l'intention
courante peut la faire dire. L'intention courante est toujours servie d'abord.

## Context

- `_eligibility` : parole durable d'une intention passée ⇒ `carried_over`
  (éligible). Commentaire à jour de la décision du 19/09.
- Sélection : `min(eligible, key=ordering_key)` = priorité puis `created_at` ⇒
  l'ancienne passe **devant** la nouvelle à priorité égale.
- Core : `_take_pending_replies` remet au cerveau les paroles de
  `_spoken_works` (celles avec `work_id` seulement) sans les retirer de la
  bouche ⇒ course.
- Voir `docs/01-decision-log.md` (28/09) et `docs/02-architecture.md`.

## Canonical Concepts

`intent_id`/`intent_epoch`, `_intent_watermark`, `SpeechCandidateStatus`,
`_decision`/`_defer`, `_replan`, `_select`, `BrainContext.pending_replies`,
`BrainPendingReply`, `MAX_BRAIN_PENDING_REPLIES`, `_promote_uncertain_turn`,
`BrainIntentRevision`, `BrainEventKind.SUPERSEDED`, diagnostic `supersession`.

## Scope

### In Scope

- **Bouche** : remplacer `carried_over` par un état non éligible
  `held_for_brain` pour toute parole durable non démarrée d'une intention
  passée ; appliquer les verdicts Core `revalidated_as` / `not_revalidated`
  (⇒ `superseded` avec raison) ; filet : parole retenue plus de
  `held_for_brain_max_s` sans verdict ⇒ `expired` tracé.
- **Ordre** : sélection = intention courante d'abord, puis priorité, puis
  date ; corriger le commentaire contradictoire.
- **Core** : suivre toute parole non transitoire par `speech_id` (plus
  seulement `work_id`), y compris les relais de la Slice 03 ; les remettre au
  cerveau à l'activation ; publier les `speech_id` remis ; en fin de tour
  **réussi**, publier le verdict par `speech_id` ; tour échoué/abandonné ⇒
  remise au tour suivant ; parole tardive d'une corrélation dépassée ⇒ ajoutée
  aux `pending_replies` du prochain tour.
- **Réémission** : le cerveau réémet par une parole normale ; Core relie la
  nouvelle parole à l'ancienne (champ explicite dans la sortie du cerveau, ou
  règle de rattachement documentée — choisir, justifier, tester). Rendu des
  `pending_replies` dans le contexte du cerveau revu : « ces phrases n'ont pas
  été dites ; redis ce qui reste utile, reformulé pour la situation actuelle ;
  sinon ne dis rien ».
- **Tests hérités** : faire évoluer, en citant la décision du 28/09,
  `test_a_durable_answer_of_a_past_intent_is_carried_over_and_spoken`,
  `test_speech_presentation_scheduler.py:34`,
  `test_a_durable_answer_spoken_past_the_revision_is_carried_over_not_stale` ;
  diagnostic `supersession` **v4** (v3 intacte).
- Faire passer T3, T4, T5, T8.

### Out of Scope

- Barge-in pendant la parole (Slice 05).
- Toute modification d'outcome, de fait public, de travail ou de dépendance.

## Dependencies

00, 01, 02, 03

## Implementation Steps

1. Freshness-check (bouche, Core, adaptateur de contexte cerveau).
2. Contrat d'évènement « remis / verdict » écrit dans
   `docs/05-event-contracts.md` avant le code.
3. Bouche : état, ordre, verdicts, filet.
4. Core : suivi par `speech_id`, remise, verdicts, remise sur échec.
5. Contexte cerveau : rendu et rattachement de la réémission.
6. Tests hérités + v4 + T3/T4/T5/T8.

## Files Likely Touched

- `jarvis/runtime/speech_scheduler.py`
- `jarvis/core/brain_service.py`
- `jarvis/domain/v2.py` (statuts / évènements)
- adaptateur de contexte cerveau (rendu `pending_replies`)
- `jarvis/testlab/virtual/runners.py` + manifeste du diagnostic
- `docs/05-event-contracts.md`

## Architecture Constraints

Une parole est soit prononçable, soit remise au cerveau, jamais les deux. Aucune
règle d'ancienneté ne décide du contenu. `supersede_stale_replies=True` n'est
pas réactivé ; le drapeau peut être retiré s'il devient mort (le dire au LOG).

## Automated Validation

T3, T4, T5, T8 verts ; suites scheduler / présentation / délégation / testlab
vertes ; `speech.stale_formulation_started_count == 0` en v4.

## Acceptance Criteria

Dans la scène du 28/09 rejouée en virtuel, B' est dite avant tout, et A n'est
dite que si le cerveau l'a réémise.

## Documentation Updates

Docstrings `_eligibility`, `_take_pending_replies` ; contrats d'évènements ;
décision du 28/09 reportée dans la doc de décisions du dépôt.

## Handoff Notes

Slice qui amende une décision utilisateur : point HV dédié. QA :
`qa-verification`, `code-review`, `runtime-validation`, `agent-trace-analysis`
(traces réelles : le cerveau reçoit bien les réponses remises et réémet à bon
escient).
