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

## 2026-09-28 — Slice 01 rework

Reprise QA (REWORK). Tests seulement, aucun code produit. Tout test neuf ou modifié reste `xfail(strict=True, reason="S0X: …")` et échoue aujourd'hui sur son assertion comportementale (lu avec `--runxfail -rf`, 3 passes identiques).

Constat → changement :

1. **T7 passait avec une file gelée pour toujours.** Ajout de T7b (bruit ⇒ reprise) et T7c (Core + job en cours non annulé). Les deux passent par le vrai bridge (`RealtimeConversationBridge._consume` sur `FakeRealtimeSession` + `FakeAudio`) : barge-in réel (`realtime.speech_started` → `voice.barge_in`), fin de parole (`speech_stopped`), puis la décision « non adressé » que le code offre aujourd'hui : transcript `hum`, classé `filler` par `noise_reason`, écarté par le bridge (`voice.transcript_dropped`). T7c : `JobService` réel relié à `BrainOrchestrator(jobs=…)`, job rattaché au `work_id` du tour ; l'assertion job (statut `running`, aucun `cancel` du worker — Décisions 15/35) passe aujourd'hui et précède celle du gel.
2. **T6 contournait le lieu réel du défaut.** Nouveau fichier `tests/unit/test_spontaneous_notice_typing.py` : vrai `ControlCenter._analyse_calibration_event` (Bare Hands actif, séance ouverte, `agent.ask` remplacé), lu à la sortie de `GET /api/agent/notices` (`ControlCenter.agent_notices`, ce que Core reçoit) et, en T6d, jusqu'au bus de Core via le vrai `ControlCenterBrainBackend.next_notices` (seul le transport HTTP est remplacé par le gestionnaire en processus) et la vraie boucle `JarvisCoreApplication._brain_notice_loop`. Assertions sur les champs `kind`, `supersedes_key`, `ttl_s`/`expires_at`, jamais sur une signature. T6e : « aucun relais sans genre » sur toute la file servie (accusé, analyse, relais de fin de sous-agent).
3. **Tour cerveau en échec absent.** T4b ajouté. T4 exige désormais `held_for_brain` avant `not_revalidated`.
4. **Faux Live plus aimable que le vrai.** `tests/fakes/live_output_surface.py` : mode `shared_output=True` (un seul id fournisseur pour des paroles enchaînées, `output_started` une fois par id, comme `openai_live_frontend.py` + `_legacy_events`) ; défaut inchangé ; docstring corrigée ; `speech_frames` par parole (l'id ne sépare plus les paroles). Variantes dans le NOUVEAU fichier `tests/unit/test_speech_scheduler_live_completion_shared_output.py` ; `test_speech_scheduler_live_completion.py` non touché (S02 y travaille).
5. **T1 sans borne basse ni statut.** Dans le nouveau fichier, paramétré sur les deux modes : écart ∈ [2,00 ; 2,75[ s, première parole `completed`/`output_completed`, jamais `delivery_not_complete`. T2 idem (statut).
6. **T4/T5 dépendaient des noms de statut.** Reconnaissance par la raison (`not_revalidated`, `revalidated_as`) sur tout statut terminal non dit (`retired()` : ni vivant, ni dit), et « jamais démarrée » (aucune décision `started/completed/interrupted`, texte absent de la surface).
7. **Lecture de `scheduler._candidates`.** Supprimée : `speech_id → texte` vient du bus de Core (`brain.speech.requested`, abonné du test) ; `queued()` croise avec `voice.speech.queued`. T5 ne dépend plus de la rétention des candidats par la bouche.
8. **Attentes en temps réel.** T3–T6b et tous les nouveaux tests tournent sous `run_virtual` ; l'ordonnanceur a une `VirtualWallClock` ; T6b attend 120 s simulées (`asyncio.sleep`) au lieu d'avancer une `FakeClock`.
9. T8 : rien (recommandation pour S04).

Tests neufs / modifiés et raison d'échec observée (`--runxfail`) :

| Test | Slice | Raison d'échec observée |
|---|---|---|
| `…live_completion_shared_output.py::test_the_next_live_speech_starts_once_the_previous_one_has_been_heard_and_not_before[output-per-speech]` (T1) | S02 | 2e phrase démarrée 30,00 s après la 1re (attendu [2,00 ; 2,75[) ; 1re `interrupted/delivery_not_complete` ; stall 1 fois |
| idem `[shared-output-like-real-live]` | S02 | idem, id fournisseur partagé |
| `…shared_output.py::test_a_short_gap_inside_a_live_speech_does_not_let_the_next_one_start_whatever_the_output_id[output-per-speech]` (T2) | S02 | départ 27,85 s après la fin réelle de l'audio (attendu < 0,75 s) ; `delivery_not_complete` ; stall 1 fois |
| idem `[shared-output-like-real-live]` | S02 | idem |
| `test_speech_presentation_revalidation.py::test_the_fresh_answer_is_said_before_an_answer_written_for_the_previous_question` (T3, virtuel) | S04 | A « Il est midi. » servie avant B' |
| `…::test_an_old_answer_the_brain_does_not_repeat_is_never_said` (T4, + `held_for_brain`) | S04 | A dite ; décisions eligible/current_intent → selected → started |
| `…::test_an_old_answer_survives_a_failed_brain_turn_and_is_judged_by_the_next_one` (T4b, neuf) | S04 | A dite après l'échec du tour N (… started → completed/output_completed), sans verdict |
| `…::test_an_old_answer_the_brain_repeats_is_said_exactly_once` (T5, virtuel) | S04 | A dite 2 fois (ancienne `completed`) |
| `…::test_the_calibration_acknowledgement_is_never_said_once_its_analysis_is_ready` (T6a, virtuel) | S03 | accusé dit avant l'analyse prête |
| `…::test_an_unsaid_calibration_acknowledgement_expires_instead_of_being_said_late` (T6b, virtuel) | S03 | accusé dit 120 s simulées après ; aucune `expired/ttl` |
| `…::test_a_queued_answer_waits_for_the_addressing_decision_after_a_barge_in` (T7, inchangé) | S05 | file repartie sans décision d'adressage |
| `…::test_a_queued_answer_resumes_once_the_barge_in_turns_out_to_be_noise` (T7b, neuf) | S05 | A démarrée avant la décision d'adressage (dès `speech_stopped`) |
| `…::test_a_barge_in_freezes_the_queue_without_cancelling_the_work_in_progress` (T7c, neuf) | S05 | job intact (`running`, 0 cancel) ; A démarrée avant la décision d'adressage |
| `test_spontaneous_notice_typing.py::test_the_calibration_notices_reach_core_typed_with_a_shared_key` (T6c, neuf) | S03 | notice servie à Core = `{seq, text, ts_ms, origin}` : pas de `kind` (ni TTL, ni clé) |
| `…::test_no_notice_reaches_core_without_an_explicit_kind` (T6e, neuf) | S03 | les 3 relais servis (accusé, analyse, fin de sous-agent) sans `kind` |
| `…::test_core_emits_the_calibration_notices_typed` (T6d, neuf) | S03 | Core publie l'accusé `kind=result`, `expires_at=None`, `supersedes_key=None` |

Points pour les Slices suivantes :
- S03 : T6c/T6d fixent `supersedes_key` préfixée `calibration:` et distincte par évènement (révision 5 vs 9), sans imposer la forme de l'id. T6d remplace `ControlCenterBrainBackend._session` par le gestionnaire de route en processus ; si S03 change la forme de l'appel HTTP (`get(url, params=…)`), adapter `InProcessNoticeRoute`.
- S05 : T7b/T7c prennent comme décision « non adressé » un transcript écarté par le bridge (`voice.transcript_dropped`, `on_ambient`) ; la bouche n'en reçoit aujourd'hui aucun signal — c'est à S05 de le câbler. Décision attendue ≤ 1 s après `speech_stopped`, reprise ≤ 1 s après.
- S04 : T4b attend le verdict `not_revalidated` au tour réussi suivant (pas de réémission) et `pending_replies` contenant A pour ce tour.

Portes : 4 fichiers (3 neufs/modifiés + `test_speech_scheduler_live_completion.py` pour le faux modifié) `--runxfail` = 18 failed ×3 (raisons identiques d'une passe à l'autre) ; sans = 18 xfailed ×3, 0 XPASS ; suite de la tâche = 733 passed, 1 skipped, 2 failed (les 2 hérités).

## 2026-09-28 — Slice 03

Relais spontanés typés, de bout en bout. Worktree `s03wt`, branche `task/jarvis-voice-stale-speech-presentation-s03`. Aucun fichier de la Slice 02 touché (`speech_scheduler.py`, `realtime_audio.py`, `live_frontend_session.py`) ; la supersession est celle qui existait (`SpeechRequest.supersedes` via `_may_supersede`, même source = même intention empruntée), le TTL celui de `_eligibility` / `OutputAdmission`.

Conception :
- Contrat unique `jarvis/domain/brain_notice.py` (`NoticeTyping` : `kind` `SpeechKind`, défaut `result` ; `supersedes_key`, `work_id` = identités bornées `speech_id()` ; `ttl_s` ∈ ]0 ; 3600]). Toute valeur hors contrat lève `ValueError`, jamais ramenée au défaut.
- Control Center : `ClaudeLocalAgent.publish_notice(text, *, origin, kind, supersedes_key, ttl_s, work_id)` valide, refus journalisé `agent.notice_refused` (error) ; `_append_notice` sert `{seq, text, ts_ms, origin, kind, supersedes_key, ttl_s, work_id}` — `kind` toujours explicite — et le recopie sur `agent.unsolicited_result`.
- Fin de sous-agent (`_push_notice`, origine `task-notification`) : `result`, `work_id` = `work_key` de la tâche quand **une seule** tâche de fond `agent` a fini depuis le relais précédent (`AgentTaskTracker.take_relayed_work_key`) ; sinon aucun, consigné `agent.notice_work_unknown`. Le `result` du CLI ne nomme pas la tâche (vérifié sur la trace réelle : `origin = {"kind": "task-notification"}` seulement).
- Core : `next_notices` rend les mappings tels que servis (pas de journal côté client) ; `_brain_notice_loop` passe les champs ; `announce_notice` revalide (refus `core.brain.notice_dropped`, `reason=invalid_notice`, error), fixe `expires_at` (`ttl_s`, sinon défaut transitoire de Core), publie via `_emit_speech(trace_kind="core.brain.notice_relayed")`. La trace `core.brain.notice_relayed` porte `speech_id` (identité de présentation, y compris d'un `result` sans `work_id`), `kind`, `supersedes_key`, `work_id`, `expires_at`, `conversation_event_id` ; le `brain.speech.requested` du relais s'y joint par `[conversation_id, speech_id]`. Un relais transitoire ne devient plus un fait public.
- Calibration : accusé `ack`, `ttl_s = CALIBRATION_ACK_TTL_S = 15 s`, analyse `result`, clé partagée `calibration:<séance>:<révision>` (`calibration_notice_key`).

TTL de l'accusé = 15 s : « viennent d'arriver » cesse d'être vrai en secondes, l'analyse arrive en quelques secondes ; 15 s laissent finir une phrase en cours sans survivre à l'écran de revue ; 3× plus court que le défaut 45 s des transitoires (pensé pour des étapes de travail longues).

Compatibilité : notice sans `kind` (Control Center ancien) → `result`, dite ; backend rendant des textes nus → `result`. `docs/legacy/untyped-brain-notices.md` (condition de retrait). Seule l'absence est tolérée.

Contrat de test ajusté (pas d'assertion affaiblie) : `test_brain_delegation.py::test_the_brain_backend_follows_the_notice_cursor` attend désormais le mapping `{text, kind: None, …}` au lieu du texte seul (nouvelle forme de retour de `next_notices`). Transport T6d inchangé : `InProcessNoticeRoute` non modifié.

**T6b non passé — test erroné, marqueur `xfail` laissé.** La scène monte l'ordonnanceur avec `output_timeout_s = TIMEOUT_S = 5 s`, et la sortie de `busy_surface` n'est pas vivante pour la session (`FakeVoiceSession.active_output_id` reste `None`) : au bout de 5 s virtuelles, `_wait_for_idle_output` constate un `output_stalled` et libère la bouche. L'accusé (TTL déclaré par le test : 20 s) démarre donc à 5,1 s, bien dans sa durée de vie, et les 120 s d'attente ne le trouvent jamais en file. Sonde (`scratchpad/s03/probe_t6b.py`) : `0.1 eligible` → `5.1 output_stalled, selected, started` → `20.1 deferred ttl` (admission) → `25.0 interrupted delivery_not_complete`. Aucune correction produit légitime ne peut le rendre vert ; il faut une correction de montage (tenir la sortie de surface vivante, ou `output_timeout_s` > 120 s) : à trancher par agent 0 / auteur du test.

Tests ajoutés : `tests/unit/test_brain_notice_contract.py` (22) — validation, refus tracés CC et Core, trace enrichie, échéance par défaut d'un `ack`, compatibilité ancien format jusqu'au bus de Core, `work_id` de sous-agent (un / plusieurs), visibilité dans le journal des évènements (`trace_entry_matches`).

Résultats :
- T6a, T6c, T6d, T6e verts, marqueurs `xfail` retirés ; T6b xfail (ci-dessus).
- Fichiers S01 : 4 passed, 15 xfailed, 0 XPASS.
- Suite de la tâche : 733 passed, 1 skipped, 2 failed (les 2 hérités).
- Autres fichiers touchant ce qui change (`test_brain_delegation`, `test_barehands_calibration_events`, `test_agent_tasks`, `test_conversation_event_subagents`, `test_conversation_event_producers`, `test_conversation_event_trace`, `test_live_lifecycle_lease_review`, `test_speech_presentation_scheduler`, `test_background_events`, `test_control_center_catalog_ui`, `test_control_center_mcp_inspector_js`, intégration `background_failure_speaks`, `conversation_event_production/rollout_gate/timeline`, `v2_async_conversation`, `work_cancel_protocol`, `work_ui_projection`, `live_brain_full_stack`) : verts sauf l'hérité de `test_brain_delegation`.

Docs : `docs/conversation-events.md` (« Spontaneous notices (typed relays) », ligne producteur de `brain.speech.requested`), `docs/barehands-contracts.md` (accusé/analyse typés), `docs/legacy/untyped-brain-notices.md`, docstrings `announce_notice`, `publish_notice`, `next_notices`, `_brain_notice_loop`, `_analyse_calibration_event`.

Écart connu : `supersedes_key` / `expires_at` ne sont pas des attributs de l'évènement `brain.speech.requested` (liste blanche `ATTRIBUTE_KEYS` de `jarvis/domain/conversation_events.py`, modifié en parallèle par la Slice 02) ; ils sont dans la ligne `core.brain.notice_relayed` jointe. Le message de cette ligne n'est pas dans `STATIC_MESSAGES` (drill-down : message masqué, données gardées) — même raison.

Reprise T6b (autorisée par agent 0, montage seulement) : la sortie de `busy_surface` est tenue vivante jusqu'à `release_surface` par `scene.scheduler.output_alive` (crochet que le bridge branche en production : la session dit sa sortie en lecture), plutôt qu'un `output_timeout_s` > 120 s qui aurait élargi le filet pour toute la scène sans modéliser une phrase en cours. Assertions inchangées, `xfail` retiré. Preuves : (a) vert sur le code produit ; (b) `announce_notice` ramené au comportement d'avant la Slice 03 (`NoticeTyping()` : `result`, sans TTL ni clé) ⇒ rouge sur `not in spoken` (accusé eligible → selected → started) ; variante `ttl_s` forcé à `None` seul ⇒ vert, l'accusé gardant `kind=ack` reçoit l'échéance par défaut de Core (45 s < 120 s). Fichier produit restauré à l'identique (sha256 vérifié). Fichiers S01 : 5 passed, 14 xfailed, 0 XPASS ; suite de la tâche : 733 passed, 1 skipped, 2 failed (hérités).
