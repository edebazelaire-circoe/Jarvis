# Execution log

Réservé aux agents d'exécution. Consigner les découvertes durables, décisions, preuves de QA et notes de passation. Un texte de planification n'est jamais une preuve de travail fait.

## 2026-09-28 — Slice 00 (agent 0)

- Branch `task/jarvis-voice-stale-speech-presentation` from `origin/main@202333d`; handoff mirrored (`2cd9fd6 S0`).
- Blind audit confirms the six README facts; extras A1–A4 (Live output id mismatch, Live barge-in mute, journal lacks `presentation_decided`, event-contract doc path). See `slices/00-project-manager/READINESS.md`.
- Baseline: Live never completed a speech (93/93 started → `delivery_not_complete` at 30.00–30.02 s, 0 ms played); 18–21/09: 32/63 interruptions at ~30 s (README's 36/74 corrected); 28/09 session found in the main journal at 12:54–12:58Z.
- Inherited reds: 10 in `tests/unit` (list in READINESS B4); gate suite 31 files = 733 passed, 1 skipped, 2 inherited failures.
- Decisions by agent 0 (Human delegated autonomy): Task Type waived; 28/09 blocker void; state **READY**.
- Issues opened: `live-barge-in-mutes-incarnation.md`, `journal-wal-corrupt.md`.

## 2026-09-28 — Slice 01

Tests rouges, tous `xfail(strict=True)`. Échecs lus avec `--runxfail` (tous sur l'assertion comportementale, aucun ImportError/TypeError/timeout de harnais) :

| Test | Slice | Raison d'échec observée |
|---|---|---|
| `tests/unit/test_speech_scheduler_live_completion.py::test_the_next_live_speech_starts_as_soon_as_the_previous_one_has_been_heard` (T1) | S02 | 2e phrase Live démarrée 30,00 s après la 1re (attendu < 2,75 s), `speech_output_stalled` émis 1 fois |
| `…live_completion.py::test_a_short_gap_inside_a_live_speech_does_not_let_the_next_one_start` (T2) | S02 | pas de départ dans le trou de 150 ms (déjà vrai), mais départ 27,85 s après la fin réelle de l'audio (attendu < 0,75 s), stall 1 fois |
| `tests/unit/test_speech_presentation_revalidation.py::test_the_fresh_answer_is_said_before_an_answer_written_for_the_previous_question` (T3) | S04 | la bouche sert A « Il est midi. » (intention N-1) avant B' « Il fait beau. » |
| `…revalidation.py::test_an_old_answer_the_brain_does_not_repeat_is_never_said` (T4) | S04 | A dite alors que le cerveau ne l'a pas réémise ; décisions de A : eligible/current_intent → selected → started |
| `…revalidation.py::test_an_old_answer_the_brain_repeats_is_said_exactly_once` (T5) | S04 | A dite 2 fois (ancienne `completed`, puis la réémission) |
| `…revalidation.py::test_the_calibration_acknowledgement_is_never_said_once_its_analysis_is_ready` (T6a) | S03 | l'accusé « Tes résultats viennent d'arriver… » dit avant l'analyse alors que l'analyse était prête |
| `…revalidation.py::test_an_unsaid_calibration_acknowledgement_expires_instead_of_being_said_late` (T6b) | S03 | accusé dit 120 s (horloge simulée) après émission ; aucune décision `expired/ttl` |
| `…revalidation.py::test_a_queued_answer_waits_for_the_addressing_decision_after_a_barge_in` (T7) | S05 | après barge-in, A démarre dès que l'utilisateur se tait, sans décision d'adressage (2 s virtuelles) |
| `tests/integration/test_testlab_stale_supersession_v4.py::test_v4_of_stale_supersession_never_starts_an_answer_written_for_the_previous_question` (T8) | S04 | trace du run : `old-result` démarrée, `new-result` jamais ; `speech.stale_formulation_started_count` non encore mesurée par le runner |

Montage et faux :
- `tests/fakes/virtual_time_loop.py` (nouveau) : boucle asyncio à temps virtuel (saute aux minuteurs quand rien n'est prêt ; gèle l'horloge tant qu'un `to_thread` est en vol). T1/T2/T7 : 30 s de filet en < 1 s réel.
- `tests/fakes/live_output_surface.py` (nouveau) : surface « Live » sans fin de sortie (`requires_local_quiescence_without_output_final`, `audio_observation_starts_output`, ids fournisseur `live-output-N` sans `speech_id`, comme l'adaptateur). Aucun faux existant ne simulait l'absence de `response_done` (`FakeVoiceSession`, `FakeRealtimeSession` en émettent).
- T1/T2 passent par le vrai `RealtimeConversationBridge._consume` (+ périphérique `ImmediateOutputStream`) câblé comme `PersistentVoiceRuntime` : la quiescence locale est bien constatée par le bridge (sondé : drain confirmé après chaque trame) — S02 n'a qu'à la faire parvenir à la bouche. Grâce bornée à 500 ms (haut de la fourchette S02).
- T3–T6 : Core réel en mémoire (`BrainOrchestrator` + `CoreEventBus` + SQLite `tmp_path`) relié à l'ordonnanceur par un client en processus ; cerveau scripté. Pas de réseau.

Points pour les Slices suivantes :
- S03 : le stimulus de T6 appelle `announce_notice` avec `kind`/`supersedes_key`/`ttl_s` **seulement si la signature les accepte** (contrat de `docs/02-architecture.md`) ; aujourd'hui l'appel reste `announce_notice(text)`. Si S03 nomme autrement ces champs, adapter le helper `announce`.
- S04 : T5 fait réémettre A par le cerveau avec le même texte, sans champ de rattachement ; si S04 choisit un champ explicite, c'est le script du cerveau qui le portera. Constat annexe : la trace de A reste `eligible/current_intent` après l'arrivée de l'intention N (le `carried_over` n'est jamais tracé pour une parole déjà en file) — trace trompeuse à corriger avec l'état `held_for_brain`.
- S04 / T8 : v4 **déclarée mais non publiée** — `tests/fixtures/testlab_unpublished/speech/stale_supersession.v4.json`. La publier dans `jarvis/testlab/official/` casserait des tests existants (`test_testlab_catalog.py` : `versions == (1, 2, 3)`, dernière = v3 ; `test_testlab_virtual_runs.py` : version par défaut 3). T8 la charge dans une copie verrouillée du catalogue. S04 : déplacer le fichier dans `official/speech/`, ajouter l'entrée du verrou (empreinte), faire évoluer ces tests, et mesurer `speech.stale_formulation_started_count` dans `_supersession_metrics`. Le scénario v4 n'a pas d'`expect.metric` sur la nouvelle métrique (non mesurable aujourd'hui → erreur `unevaluable`, mauvaise raison d'échec).
- S05 : T7 suppose que la décision d'adressage arrive en ≤ 2 s ; aucune décision n'est envoyée dans le test.

Portes : fichiers neufs `--runxfail` = 9 failed (raisons ci-dessus) ; sans = 9 xfailed, 0 XPASS ; suite de la tâche = 733 passed, 1 skipped, 2 failed (les 2 hérités) ; `test_testlab_catalog.py` 49 passed.
