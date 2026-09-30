# Tests et qualité

## Portes automatiques

- **Fin de parole Live** : une phrase de ~2 s sur une surface
  `requires_local_quiescence_without_output_final` libère la bouche en
  < durée audio + grâce + 250 ms ; `speech_output_stalled` jamais émis sur le
  chemin nominal ; la parole suivante ne démarre jamais tant que l'audio de la
  précédente arrive encore (trou entre blocs < grâce).
- **Parité classique** : sur une surface avec `response_done`, comportement et
  traces inchangés.
- **Tour de retard** (conversation accélérée, testlab virtuel) : A prête,
  l'utilisateur dit B, le cerveau produit B', A non démarrée ⇒ A ne démarre
  jamais avant B', et ne démarre jamais du tout sans réémission.
- **Revalidation** : cerveau qui réémet ⇒ la nouvelle formulation est dite une
  fois ; cerveau qui ne réémet pas ⇒ rien n'est dit, trace `not_revalidated` ;
  tour cerveau échoué ⇒ la parole reste retenue et arrive au tour suivant.
- **Relais** : l'accusé de calibration expire (TTL) ou est remplacé par
  l'analyse ; jamais dit après elle ; aucun relais sans genre.
- **Interruption** : barge-in pendant la parole ⇒ file gelée jusqu'à la
  décision d'adressage ; tour non adressé ⇒ reprise ; aucun job/sous-agent
  annulé (asserté sur Core).
- **Invariants** : la vérité Core (outcomes, faits publics, travaux) n'est
  jamais modifiée par une décision de présentation.
- Suites existantes vertes : `test_v2_speech_scheduler.py`,
  `test_speech_presentation_scheduler.py`, `test_speech_presentation.py`,
  `test_speech_scheduler_review_races.py`, `test_brain_interrupted_speech.py`,
  `test_realtime_audio_lifecycle.py`, `test_openai_live_frontend*.py`,
  `test_brain_delegation.py`, `test_back_brain_delegation.py`,
  `test_barehands_calibration_*`, `test_testlab_virtual.py`,
  `tests/integration/test_testlab_virtual_runners.py`,
  `tests/integration/test_voice_replay_regressions.py`,
  `tests/integration/test_background_failure_speaks.py`.

## Composition QA

Toute Slice : `qa-verification`. Code : + `code-review`. Comportement vocal /
runtime : + `runtime-validation`. Contexte ou prompt du cerveau
(`pending_replies`, consignes de réémission) : + `agent-trace-analysis` sur
traces réelles.

## Métriques de clôture (Slice 06)

| Métrique | Cible |
|---|---|
| Libération bouche Live après quiescence, p95 | < 1 s |
| `speech_output_stalled` sur Live, session nominale | 0 |
| Paroles d'une intention dépassée démarrées sans réémission | 0 |
| Attente en file des paroles de l'intention courante, p95 | < 2 s au-delà de la parole en cours |
| Relais sans genre / sans TTL ni clé | 0 |
