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

## 2026-09-28 — Slice 02

Fin de parole Live par preuve locale. Freshness-check : fonctions citées identiques à `a34029a` (`_await_output`, `note_output_event`, `_note_live_output_quiescent`, `output_pending`, `_enqueue`).

**Registre de lecture Core — verdict : ne donne pas de fin par sortie sur Live.** `LiveFrontendSession.observe_playback(..., terminal=True)` (`live_frontend_session.py:384-402`) n'est appelé en `terminal=True` que sur une admission invalidée ou un périphérique jamais prêt (`realtime_audio.py` `_play_audio`) ; le chemin nominal l'appelle en `terminal=False`. Les sorties Live ne sont soldées qu'à l'apparition d'une nouvelle identité fournisseur (`_settle_previous_outputs`, statut `UNKNOWN`, « no delivery claim »), identité qui n'est renouvelée qu'au retour de la parole utilisateur (`openai_live_frontend.py:407,427,531`) : deux paroles Jarvis consécutives partagent la même. `playback_manifest` / `observe_device_completion` ne servent que sur `realtime.response_done` (`_complete_device_output`), absent de Live. Aucune clé ne relie ces sorties à l'`output_id` réservé par la bouche. → Signal bridge → bouche ajouté, en réutilisant le câblage existant `on_output_event` (aucun changement de `voice_v2.py`).

**Chemin du signal.**
- `jarvis/domain/voice_playback.py` : `LIVE_OUTPUT_AUDIBLE = "realtime.output_audible"`, `LIVE_OUTPUT_QUIESCENT = "realtime.output_quiescent"`.
- Bridge (`realtime_audio.py`) : `_note_first_audio` relaie AUDIBLE à la première écriture périphérique réussie depuis la dernière quiescence (ou d'une nouvelle sortie fournisseur) — une fois par rafale, pas par trame ; `_note_live_output_quiescent` relaie QUIESCENT (drain natif prouvé ou réconciliation tardive) avant le retour de surface. Seulement si `requires_local_quiescence_without_output_final`.
- Bouche (`speech_scheduler.py`) : `note_output_event` → `_note_live_playback` (ignoré hors Live) : AUDIBLE ⇒ `audio_heard`, grâce annulée ; QUIESCENT après audio ⇒ grâce armée (`call_later`) ; `_complete_on_quiescence` ⇒ `status="completed"`, `completion_basis="local_quiescence"`, `release_after_quiescence_ms`, `done.set()`. L'audio est attribué à la parole en cours de livraison (la bouche est seule à appeler `speak`), jamais à une identité fournisseur : marche avec une sortie fournisseur partagée. Limite documentée : un audio que le modèle Live dirait de lui-même pendant une parole dispatchée lui est crédité.
- `_await_output` : sur Live, attente du premier audio bornée par `live_first_audio_timeout_s` ; sans audio ⇒ `unconfirmed` (trace `voice.speech.output_unconfirmed`, warning, `code=speech_output_unconfirmed`), candidat `completed/output_unconfirmed`, chaîne avancée, pas de `delivery_not_complete`. Le filet `OUTPUT_TIMEOUT_S` reste (compté : `output_stall_count`, `stall_count`, `without_output_final`, `audio_heard` dans `speech_output_stalled`). Barge-in pendant la grâce : `interrupted` lu en premier par `_speak` ⇒ l'interruption l'emporte.

**Constantes.** `SpeechScheduler.LIVE_COMPLETION_GRACE_MS = 500` (kwarg `live_completion_grace_ms`) : haut de la fourchette, parce que les blocs silencieux Live sont jetés avant lecture (`is_silent_pcm16`, mesure du 21/09 dans `docs/voice-architectures/INDEX.md`) : le périphérique se draine donc aussi à chaque pause entre phrases d'une même réponse ; la grâce doit couvrir cette pause, pas seulement la gigue des blocs de 100 ms. Critère toujours tenu (grâce + 250 ms, p95 < 1 s). Longueur réelle des pauses à mesurer en Slice 06 ; si elle dépasse 500 ms, une fin prématurée ne fait que dispatcher la parole suivante plus tôt (append Live). `LIVE_FIRST_AUDIO_TIMEOUT_S = 8.0` (kwarg `live_first_audio_timeout_s`) : latence append → premier PCM de GPT-Live de quelques secondes, marge ×2 ; très en deçà des 30 s.

**Fusion des chunks Live dans `_enqueue` : gardée.** Enchaîner les paragraphes mettrait la grâce (500 ms) en silence entre chacun, sans gain : la surface découpe déjà en ajouts bornés. Commentaire mis à jour.

**Journal / timeline (réparation A2).** `completion_basis` et `release_after_quiescence_ms` sur `voice.speech.completed` et sur l'évènement `mouth.speech.completed` (ajoutés à `ATTRIBUTE_KEYS`, `domain/conversation_events.py`) ; allowlist du drill-down de trace (`conversation_event_trace.py` `TRACE_CODE_KEYS`/`TRACE_NUMBER_KEYS`) ; libellés de la timeline (`control_center_timeline.js`). Surface classique : `completion_basis=provider_response_done`, rien d'autre ne change.

**Docs.** Docstrings `_await_output`, `_without_output_final`, `_note_live_output_quiescent`, `_ActiveSpeech`, `_note_live_playback` ; contrat Live dans `docs/ARCHITECTURE.md` « Speech, interruption and work » ; `docs/conversation-events.md` (ligne `mouth.speech.completed`, attributs, `ATTRIBUTE_KEYS`) ; renvoi dans `docs/voice-architectures/INDEX.md`.

**Tests.**
- T1, T2 (`test_speech_scheduler_live_completion.py`) : verts, `xfail` retirés (seul changement du fichier).
- Nouveau `tests/unit/test_speech_scheduler_live_end_of_speech.py` (7) : sortie fournisseur **partagée** et un seul `output_started` (faux local `SharedOutputLiveSurface`) — écart ≥ 2,0 s et < 2,0 + grâce + 0,25 s, décision `completed/output_completed`, `local_quiescence`, visible en `mouth.speech.completed` ; rafales à 150 ms sur sortie partagée ; `unconfirmed` à 8 s sans blocage de chaîne ni filet ; barge-in pendant la grâce ⇒ `interrupted`/`user_barge_in` ; filet sur Live = warning compté ; bridge : AUDIBLE/QUIESCENT alternés (une fois par rafale) ; **parité classique** (preuves Live ignorées, pas de délai premier audio, `provider_response_done`).
- Portes : suite de la tâche = **733 passed, 1 skipped, 2 failed** (les 2 hérités) ; fichiers important les modules touchés + `test_v2_continuous_live.py` + `test_conversation_event*.py` + T1–T8 : 425 passed, 4 skipped, 1 xfailed (T8) et 1449 passed, 6 xfailed (T3–T7) ; `test_documented_routes.py` 3 passed. T3–T8 restent `xfail(strict)`.
