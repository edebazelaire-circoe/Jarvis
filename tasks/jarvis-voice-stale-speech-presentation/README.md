# Jarvis — Parole périmée : fin de parole Live et présentation revalidée

## But

Supprimer le « métro de retard » de la conversation vocale : Jarvis ne doit plus
prononcer au tour N une réponse rédigée pour le tour N‑1, ni réciter des
annonces devenues fausses parce que l'utilisateur a reparlé entre-temps.

Deux causes distinctes, vérifiées dans le code au 28/09/2026 :

1. **Bug de runtime — fin de parole Live.** Sur GPT‑Live
   (`LiveFrontendSession.requires_local_quiescence_without_output_final = True`),
   le fournisseur n'émet jamais `realtime.response_done`. Or
   `SpeechScheduler._await_output` (`jarvis/runtime/speech_scheduler.py`) n'est
   libéré que par cet évènement (`note_output_event`). Le bridge constate bien
   la fin locale de lecture (`_note_live_output_quiescent`,
   `jarvis/runtime/realtime_audio.py`) mais ne la transmet qu'à l'orbe. Chaque
   parole Live occupe donc la bouche jusqu'à `OUTPUT_TIMEOUT_S = 30.0` et finit
   en `delivery_not_complete`. Preuve locale (journal Core 18–21/09) : 36 des 74
   paroles « interrompues » durent 29,9–30,0 s.
2. **Défaut d'architecture — vérité durable ≠ formulation prononçable.**
   - `_eligibility` reporte (`carried_over`) toute parole durable
     (RESULT/QUESTION/ERROR) d'une intention passée sur l'intention courante.
   - La sélection `min(eligible, key=ordering_key)` trie par priorité **puis
     date de création** : à priorité égale, l'ancienne réponse A passe **devant**
     la réponse fraîche B' — c'est le mécanisme exact du tour de retard (le
     commentaire de `_eligibility` affirme l'inverse).
   - Core remet bien les réponses non dites au cerveau (`_take_pending_replies`,
     `pending_replies`), mais pendant ce temps l'ancienne formulation reste
     prononçable : course.
   - `_spoken_works` n'enregistre que les paroles avec `work_id` ; tout le canal
     des relais spontanés (`BrainService.announce_notice`) crée des
     `RESULT / NORMAL / sans work_id / sans TTL / sans supersedes_key` — y
     compris l'accusé « Tes résultats viennent d'arriver, je les analyse. »
     (`CALIBRATION_ANALYSIS_ACK`) et l'analyse de calibration elle-même. Ce sont
     des paroles éternelles, invisibles au mécanisme de revalidation.
   - Interruption asymétrique : couper pendant la réflexion purge le tour
     (`abandon_turn`) ; couper pendant la parole coupe l'audio mais laisse la
     file intacte.

## Invariant central

> **Un résultat peut rester vrai indéfiniment sans que la phrase préparée pour
> l'annoncer reste prononçable indéfiniment.**
>
> La vérité (Outcome, faits publics, travail) appartient à Core et au cerveau.
> Une `SpeechRequest` est une *tentative de présentation* liée à l'intention qui
> l'a vue naître. Quand l'utilisateur reprend la main, les présentations non
> commencées cessent d'être prononçables d'elles-mêmes ; le cerveau, qui les
> reçoit en contexte, décide de les redire — reformulées pour le nouveau
> contexte — ou non.

Cet invariant **amende** la décision utilisateur du 19/09/2026 (« une réponse
sans retard faut qu'elle soit dite si c'est cohérent avec le contexte ») sans la
renier : la cohérence reste jugée par le cerveau, jamais par une règle
d'ancienneté ; ce qui change, c'est que **pendant** ce jugement la vieille
formulation est retenue au lieu d'être servie en premier. Voir
`docs/01-decision-log.md`.

## Identité

- Projet : **Jarvis** — dépôt `edebazelaire-circoe/Jarvis`, base `main`
- Snapshot inspecté : `origin/main` `202333db5c5dea31258125a0ef296314d9b82b34`
  (28/09/2026 ; aucun fichier concerné n'a bougé depuis `76ee0fe`)
- Destination file Drive : `Jarvis/task/to-do/jarvis-voice-stale-speech-presentation/`

## Ce que la tâche ne fait pas

- Ne tue ni jobs ni sous-agents (Décisions 15 et 35 préservées).
- Ne réactive pas `supersede_stale_replies=True` (ancienne péremption en bloc,
  qui invalidait la *dépendance* et cachait la réponse au cerveau).
- Ne touche pas au pipeline classique (non Live) au-delà de ce que les tests de
  parité exigent : ce pipeline reçoit bien `response_done`.

## Démarrage du Project Manager

1. Ouvrir `slices/TODO.md`.
2. Exécuter soi-même la Slice `00-project-manager` (ne pas la déléguer).
3. Audit à l'aveugle du code courant avant de lire les conclusions ci-dessus ;
   confirmer ou corriger chaque fait (lignes citées = snapshot `202333d`).
4. Atteindre `READY` avant toute implémentation ; freshness-check ciblé avant
   chaque Slice.
5. Une Slice d'implémentation par worktree ; S02 et S03 peuvent tourner en
   parallèle dans deux worktrees distincts, tout le reste est séquentiel.
