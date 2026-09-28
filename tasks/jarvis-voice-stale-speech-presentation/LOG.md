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

### Slice 02 rework

Verdict QA : REWORK limité (6 points). Base : `f324139` (reprise S01 fusionnée : faux `shared_output=True`, `speech_frames`, juge `test_speech_scheduler_live_completion_shared_output.py`).

1. **T2 aveugle à un départ prématuré (MAJEUR) — corrigé dans les trois fichiers.** Les frames de la phrase 1 étaient lues au moment où la phrase 2 part, donc `spoken_at[1] >= audio_end` était vrai par construction. Désormais chaque T2 attend que la phrase 1 ait rendu TOUT son audio (nombre de trames du plan) avant de lire `speech_frames[0]` / les trames de `live-output-1` ; toutes les autres assertions sont identiques (édition des juges S01 autorisée par agent 0). Preuve par mutation (`LIVE_COMPLETION_GRACE_MS = 50`, restauré octet pour octet, `cmp` OK) : 5 échecs — T2 d'origine, T2 partagé ×2 modes (« démarré à 1.03 s, pendant l'audio de la première (fin à 2.15 s) »), `test_a_gap_shorter_than_the_grace…` et `test_a_pause_between_sentences…` ; tout passe à 500 ms. Les 4 `xfail` du juge partagé retirés (ils XPASSaient).
2. **Sous-classe du faux supprimée (MAJEUR).** `SharedOutputLiveSurface` retirée ; les tests utilisent `LiveOutputSurface(plan, shared_output=True)` et `speech_frames`.
3. **`unconfirmed` n'est plus une complétion (MAJEUR).** Terminal distinct, ni completed ni interrupted : `SpeechCandidateStatus.UNCONFIRMED` (raison `no_audio_observed`) ; trace dédiée `voice.speech.unconfirmed` (warning, `code=speech_output_unconfirmed`, `completion_basis=unconfirmed`) qui remplace `voice.speech.output_unconfirmed` ; nouvel évènement `mouth.speech.unconfirmed` (fermeture de span, DIAGNOSTIC : rien ne prouve que le texte a été entendu). Ajouter un type est prévu par le contrat (« update the enum, `_SPECS`, this table and the tests together », `docs/conversation-events.md`), sans changement de `schema_version` ; le store SQLite dérive ses types connus de l'enum. Répercuté : `SPAN_OPENER`, `conversation_transcript` (`PLAIN_EVENT_TYPES`, `_STATUS` « non confirmé », note « aucun son observé, écoute non confirmée »), timeline JS (table des types, `SPAN_OPENER`, libellé, ton warn), `STATIC_MESSAGES` du drill-down, DiagnosticBundle (`SpeechOutcome.UNCONFIRMED` ajouté à `TERMINAL_OUTCOMES` — aucune valeur existante ne convenait : `unknown` veut dire « aucune source voix lue » ; mappé depuis `mouth.speech.unconfirmed` et `voice.speech.unconfirmed`, jamais `spoken`), `SPEECH_TERMINAL_KINDS` des runners testlab (sinon l'attente d'un terminal pendrait ; `== "voice.speech.completed"` reste faux pour lui), `docs/testlab.md`. Pas de tour assistant persisté. `voice.speech.completed` ne porte plus que `provider_response_done` | `local_quiescence`. Chaîne toujours non bloquée.
4. **Gardes testées (MINEUR).** `test_a_quiescence_before_any_audio_of_the_speech_does_not_start_the_grace` (tue M2) et `test_a_repeated_quiescence_does_not_push_the_end_further` (fin mesurée depuis la PREMIÈRE quiescence, < grâce + 50 ms ; tue M3). Mutants vérifiés à la main, fichiers restaurés (`cmp`).
5. **Pause entre phrases > grâce (MINEUR).** Limite documentée dans `docs/ARCHITECTURE.md` à côté de l'autre : une pause plus longue que la grâce termine N trop tôt, N+1 part, et sur id partagé la fin de N est créditée à N+1. Test qui fige le comportement actuel pour une pause de 450 ms < 500 ms (pas de départ prématuré). **Slice 06 doit mesurer la distribution réelle des pauses entre phrases d'une réponse Live** (écarts de quiescence au sein d'une même parole dans `trace.jsonl`) et réviser `LIVE_COMPLETION_GRACE_MS` si le p95 dépasse 500 ms.
6. **AUDIBLE une fois par rafale (OBSERVATION) — fait sans nouveau faux de périphérique.** `test_audibility_is_relayed_once_per_burst_even_when_the_burst_spans_many_blocks` : dix blocs remis d'un coup au flux fournisseur ; le bridge les distribue tous avant la lecture, le périphérique ne se draine pas entre eux ⇒ exactement un `output_audible`. Tue M14 (garde retirée ⇒ 10 relais).

Portes : fichier S02 = 11 passed ; T1/T2 + juge partagé = 6 passed ; suite de la tâche = **733 passed, 1 skipped, 2 failed** (les 2 hérités ; les fichiers S02 n'y sont pas) ; fichiers important les modules touchés (dont testlab bundle/runners, transcript, timeline) + `test_v2_continuous_live.py` + `test_conversation_event*.py` + juges S01 : 649 passed, 13 skipped, 1 xfailed (T8) et 1946 passed, 12 xfailed (T3, T4, T4b, T5, T6a–e, T7, T7b, T7c), **0 XPASS**, 0 failed.

## 2026-09-28 — agent 0: Slices 01 and 02 accepted

- S01: QA REWORK (8 findings: judges gameable, real bug site bypassed, failed-brain-turn case missing, Live fake kinder than reality) → rework `c1a4097`, verified 19 xfail strict; merged into the task branch as `f324139`.
- S02: QA REWORK (T2 blind to premature release, `unconfirmed` counted as spoken, guards untested) → rework `b31ef8f`. Agent 0 re-verified the key mutant: `LIVE_COMPLETION_GRACE_MS = 50` → 5 failures (T2 ×3 variants, restart-grace, 450 ms pause), 17/17 green at 500 ms. The 4 shared-output judges pass without xfail.
- Human validation HV-VOICE-STALE-02 (real Live session) deferred to the final Human review, after Slice 06 measures real pauses between sentences.

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

### Slice 03 rework

Reprise QA (REWORK), sur la branche de tâche après fusion (`f734c55`), checkout principal.

1. **MAJEUR — `work_id` faux sur un relais.** `AgentTaskTracker._finish` met désormais en file **toute** tâche de fond finie, non interrompue : `(rattachable, clé)`, rattachable seulement pour un sous-agent `agent` à `work_key` ; une commande est un marqueur, donc tout mélange est ambigu. `take_relayed_work_key` ne rend une clé que pour **une seule** entrée rattachable (raisons `no_finished_background_task`, `finished_task_not_a_subagent`, `several_finished_background_tasks`). Nouveau `forget_unrelayed()`, appelé après **chaque** `result` du CLI par `ClaudeLocalAgent._on_result` (qui enveloppe `_resolve_pending`) : une fin absorbée par un autre tour n'est plus rattachée plus tard. Tests : sonde QA (sous-agent puis commande ⇒ `None`), commande seule, fin absorbée, tâche interrompue non candidate (mutant M24).
2. **MINEUR — TTL minuscule / boucle tuée.** `MIN_NOTICE_TTL_S = 1.0` (en deçà la parole serait périmée avant publication, et `SpeechRequest` refusait l'échéance). `_brain_notice_loop` : chaque relais passe par `_announce_one_notice`, qui trace une annonce en échec (`core.brain.notice_dropped`, `reason=announce_failed`, error) et laisse passer les suivants ; la lecture en échec est tracée (`core.brain.notice_poll_failed`, error) avant la pause de 5 s. Tests : bornes 1e-7 et 0,5 refusées, 1,0 acceptée ; boucle en temps virtuel (lecture qui lève puis relais qui lève ⇒ deux traces, le relais suivant est dit, la boucle vit).
3. **MINEUR — `notice_relayed` sans publication.** `_emit_speech` rend `_SpeechEmission(published, event_id, reason)` ; un relais retenu (`ambiguous_work_dependency`, `semantic_chunk_capacity`, `work_cancelled`) donne `core.brain.notice_dropped` (warning, raison réelle), ni `notice_relayed` ni fait public, et `announce_notice` rend False. Test par la vraie branche « travail annulé par le cerveau » (dépendance invalidée).
4. **Intégration.** `ATTRIBUTE_KEYS` += `supersedes_key`, `expires_at` ; `_record_speech_requested` les écrit quand ils existent (`expires_at` ISO) — pour toute parole, pas seulement les relais ; `STATIC_MESSAGES` += `core.brain.notice_relayed` ; `TRACE_ID_KEYS` += `supersedes_key`. Test : l'évènement `brain.speech.requested` d'un accusé relayé porte les deux attributs, celui d'un `result` sans clé ni échéance n'en porte aucun.
5. **Découvert en relançant les fichiers qui importent le code touché** : la garde `test_presentation_response_policy.py::test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole` échouait depuis la fusion de la Slice 03 (`kind=typing.kind` : nature venue d'un champ transporté). Correction produit : `NOTICE_KINDS = (ack, progress, result)` — `error` et `question`, natures de sûreté que la matrice laisse passer malgré le plafond, sont refusées à un relais — et `announce_notice` pose la nature par littéraux (`SpeechKind.ACK if … else SpeechKind.PROGRESS if … else SpeechKind.RESULT`). Site déclaré dans `SPEECH_KIND_SITES` (la table que la garde prévoit pour un site nouveau), avec commentaire. Tests : `error` et `QUESTION` refusés.
6. **T6b après fusion** : vert ; `announce_notice` ramené à `NoticeTyping()` ⇒ rouge sur `not in spoken` (eligible → selected → started) ; fichier restauré (sha256 identique avant/après).
7. **Décision** : amendement daté dans `docs/01-decision-log.md` (« Relais spontanés typés »).

Docs : `docs/conversation-events.md` (genres admis, borne du TTL, rattachement, refus/retenue, boucle, attributs, liste `ATTRIBUTE_KEYS`).

Portes :
- Ensemble combiné (suite de la tâche + fichiers S01/S02/S03) : **789 passed, 1 skipped, 2 failed (hérités), 8 xfailed, 0 XPASS** (777 + 12 tests neufs). Une passe intermédiaire a vu `test_barge_in_sustain.py` rouge une fois (raison `barge_in_local_voice_too_short`, minutage sous charge) : 14/14 seul, vert aux deux passes suivantes.
- Les 117 fichiers de test qui importent `agent_tasks`, `claude_local`, `v2_app`, `brain_service`, `brain_notice`, `conversation_events`, `conversation_event_trace` (2 lots) : 883 passed, 5 skipped, 1 failed (hérité `test_brain_delegation`) + 2104 passed, 7 xfailed. `test_presentation_integration.py::test_une_source_evincee_par_son_propre_rangement_n_est_pas_citee` rouge une fois dans le premier passage du lot 2, vert seul et au passage suivant (instable, hors périmètre).

## 2026-09-28 — agent 0: Slice 03 accepted

- QA REWORK (wrong sub-agent `work_id` on a shell relay — proven by probe; tiny TTL killed the relay loop silently; `notice_relayed` on a withheld relay; untested interrupted-task case) → merged `f734c55`, rework `5b45889` in the main checkout.
- Agent 0 accepts the `SPEECH_KIND_SITES` registration in `test_presentation_response_policy.py` (the guard's own mechanism; relay kinds limited to ack/progress/result, safety kinds refused).
- Flaky, not ours: `test_presentation_integration.py::test_une_source_evincee_par_son_propre_rangement_n_est_pas_citee` fails 1/10 at HEAD **and** 1/10 at `202333d` — inherited flake. `test_barge_in_sustain.py` 10/10 at HEAD (one isolated failure seen by the implementer under memory pressure) — watched.
- Combined gate after rework: 789 passed, 1 skipped, 2 inherited, 8 xfailed (S04: T3, T4, T4b, T5, T8; S05: T7, T7b, T7c), 0 XPASS.
- HV-VOICE-STALE-03 (real calibration) deferred to the final Human review.
