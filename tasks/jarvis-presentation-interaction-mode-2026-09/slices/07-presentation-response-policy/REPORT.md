# Slice 07 — Presentation response policy

Silence becomes a first-class successful outcome. A Presentation turn that
completes with zero `SpeechRequest` is normal, enforced by a runtime contract,
and readable afterwards as a success rather than as an absence.

Canonical documentation: **`docs/presentation-response-policy.md`** (new),
cross-linked from `docs/interaction-mode.md` and `docs/ARCHITECTURE.md`.
Conformance suite: **`tests/unit/test_presentation_response_policy.py`**, 119
tests after the rework (91 in round 1).

**Section 9 records the rework** and supersedes, where they disagree, the
round-1 claims in sections 1–8: the safety exception moved into the matrix, the
policy became reachable on the three typed voice architectures, and three
statements in this report were wrong and are corrected in place.

---

## 1. What was built

### New modules

| File | What it is |
| --- | --- |
| `jarvis/domain/presentation_response.py` | The judgement: classify an addressed turn into a `PresentationSituation`, then read the matrix through `may_speak()` to admit or refuse. Pure, no I/O. (Round 1 also re-situated kinds here; the rework moved that into the matrix.) |
| `jarvis/runtime/presentation_speech_gate.py` | `PresentationSpeechGate` — per-turn situation memory, verdicts, bounded accounting, and the journal lines that make silence readable. It reads the matrix rather than nuancing it; its own two rules are named in §2. |
| `tests/unit/test_presentation_response_policy.py` | The conformance suite for all three layers. |
| `docs/presentation-response-policy.md` | The contract page. |

### Changed modules

| File | Change |
| --- | --- |
| `jarvis/runtime/speech_scheduler.py` | Builds the gate; consults it at **three** call sites (`_enqueue`, `request_conversation`, `_decide_reflex`); adds `note_addressed_turn()`; settles the gate on `stop()`. (`presentation_turn_outcome()` existed in round 1 and was **deleted in rework** — no production caller, and a second name for `PresentationSpeechGate.outcome()`.) |
| `jarvis/runtime/realtime_audio.py` | New optional `on_addressed_turn` callback on `RealtimeConversationBridge`, called once per continuous addressed turn on **both** paths: after the brain submit, and in the direct-conversation branch with the admission's own correlation (the rework's B1 fix). |
| `jarvis/runtime/voice_v2.py` | Wires `on_addressed_turn=speech.note_addressed_turn` in the one composition that builds a `SpeechScheduler`. |
| `jarvis/domain/presentation_policy.py` | **Rework:** `safety_speech_kinds` on `PresentationOutputPolicy`, its two construction invariants, `UNADDRESSED_SAFETY_KINDS`, and `may_speak()` folding both columns. |
| `jarvis/runtime/back_brain_delegation.py` | **Rework:** a delegation refusal is `SpeechKind.ERROR`, not `ACK`. |
| `jarvis/domain/reflex_policy.py` | Pure extraction of `normalized_tokens` / `normalized_phrase` out of `conversational_wait_reason`, **no behaviour change**, so the situation classifier reads transcripts exactly as the reflex policy already does. |
| `jarvis/adapters/control_center_brain.py` | `observe_interaction_mode()` (optional backend capability) plus `interaction_mode` in the per-turn context, **absent at the default mode**. |
| `jarvis/core/v2_app.py` | Subscribes the brain backend to `InteractionModeService`, detected structurally like `next_notices`. |
| `jarvis/runtime/control_center.py` | `BRIEF_PRESENTATION_MODE`, rendered by `build_agent_brief` only when the context says presentation. |
| `tests/unit/test_v2_speech_scheduler.py` | `build_scheduler` gains two additive kwargs (`interaction_mode`, `reflex_delay_s`). |
| `docs/interaction-mode.md`, `docs/ARCHITECTURE.md` | Cross-links plus one paragraph each. |

---

## 2. Where the enforcement boundary sits, and why there

`SpeechScheduler` is already the single owner of what gets said and in what
order. Everything that can produce audio in continuous mode passes through it:
Core's `brain.speech.requested`, `enqueue_controller_speech`, Duplex's
`request_conversation`, and the surface reflex. Putting the policy anywhere
else would mean putting it in more than one place.

| Call site | Gates | Why exactly there |
| --- | --- | --- |
| `_enqueue`, **after** the duplicate/capacity checks | every `SpeechRequest` | before the queue, so a refused speech never becomes a candidate; after deduplication, so a Core retransmission is not counted twice (mutation M40) |
| `request_conversation` | the direct spoken answer of **SIMPLE, FRONT_BRAIN and DUPLEX** | Presentation must not be silent in one architecture and talkative in another for the same sentence. Round 1 said "Duplex" and tested only Duplex; §9 B1 is what that cost |
| `_decide_reflex` | the surface preamble | the only filler the surface produces on its own |

**Corrected in rework.** "The gate holds no policy" was too strong. The matrix
decides *what gets said*, and the gate asks it and applies the answer without
nuancing it. Two rules are the gate's own, because they are not matrix rows:
`allows_preamble()` (a preamble is nobody's speech — a contentless turn of the
surface), and the fall-back to `UNADDRESSED_SAFETY_KINDS` when a speech belongs
to no classified turn. Everything else it holds is situation memory, counts and
journal. Outside PRESENTATION it records nothing, admits everything and writes
no journal line at all — and since rework, **not even one**: the fail-open
warning on an unreadable mode is gone, because the guard could not be reached.

**The prompt is no longer the enforcement.** The `BRAIN_DISPLAY_PROMPT` lines in
`claude_local.py` stay as they are: they are applied in assistant mode too,
where "quelques mots suffisent" is correct, and changing them would move Simple
(D14). The alignment is Presentation-scoped and rides on the **turn** context,
not the session, because the mode changes hot (D15):
Core, then `observe_interaction_mode`, then `_turn_context`, then
`build_agent_brief`, then `BRIEF_PRESENTATION_MODE`. At the default mode the
context key is absent, so an assistant turn's context is byte-for-byte what it
was before this slice.
`test_le_contrat_tient_meme_si_le_modele_n_a_jamais_lu_la_consigne` proves the
runtime holds with no instruction anywhere in the loop.

---

## 3. How the classifier decides

It runs **once**, when the bridge submits an addressed turn. The transcript is
read and discarded; only the situation and a short evidence marker are kept.
Reading order is the contract:

1. explicit speak request (dis-moi, raconte, lis-moi, a voix haute), **not
   under a negation**, becomes `EXPLICIT_SPEAK_REQUEST`;
2. a question word **opening** the phrase becomes `KNOWLEDGE_QUESTION`;
3. a display verb (montre, affiche, ouvre, masque, epingle, archive, range)
   becomes `VISUAL_COMMAND`;
4. a question mark becomes `KNOWLEDGE_QUESTION`;
5. otherwise `KNOWLEDGE_QUESTION`, evidence `no_visual_command_evidence`.

Steps 1 and 4 moved in the rework: round 1 put the question mark at step 2,
where it beat the display verb and made « Tu peux montrer le bilan ? » speak —
the filler D09 removes, on the most natural phrasing. Step 2 stays ahead of the
verb so « pourquoi tu as affiché le Q3 ? » remains a question. See §9.

### "montre-moi le bilan et dis-moi le total", worked through

Normalised through the shared `normalized_phrase`, wake word stripped:
`montre moi le bilan et dis moi le total`.

Step 1 scans the speak-request markers over the space-padded phrase and finds
`" dis moi "`. The turn is an `EXPLICIT_SPEAK_REQUEST`, evidence
`speak_request:dis_moi`. That row has `voice_allowed=True` and admits all five
speech kinds, so the spoken half happens; the display half is unaffected,
because the gate only ever touches speech.

Step 1 has to come first because `VISUAL_COMMAND` carries `voice_allowed=False`
as a **hard ceiling, not a default** (the constraint carried forward from Slice
01): under that row no amount of asking unlocks speech, so a sentence asking
for both must be classified on the side where the voice exists, or its spoken
half would be dropped with no recourse and no recovery path.

Strip the speak request and the ceiling shows itself: "montre-moi le bilan"
gives `visual_verb:montre`, and `ACK`, `PROGRESS` and `RESULT` are all refused.
Both halves of this are one test,
`test_montre_moi_X_et_dis_moi_Y_ne_peut_pas_etre_une_commande_visuelle`.

### Two deliberate biases, both defended by a test

- **Silence requires positive evidence.** Step 4 answers rather than mutes.
  Muting an addressed turn we failed to parse is a silent failure: the exact
  defect this slice abolishes, and one this repository already paid for
  (`voice.speech.error_withheld` exists because of a real incident on
  16/09/2026). Test: `test_le_silence_exige_une_preuve_positive`.
- **Question words only at the head.** "ou" is an ordinary conjunction;
  matching it anywhere turns "affiche le graphique ou le tableau" into a
  question and steals the sentence from the display verb that carries it.
  Mutation M21 proves the suite catches the loose version.

### The two safety kinds

`SAFETY_SITUATIONS` judges `ERROR` on `COMMAND_ERROR` and `QUESTION` on
`KNOWLEDGE_QUESTION`, whatever the turn's own situation. The error half is the
path Slice 01 already blessed. The question half is the same argument: a turn
where Jarvis could not ask *which* bilan would die with no screen and no
sentence, and the user would not even know to ask again. A visual command that
needs a question back is not a *completed* visual command.

**Promotion is refused for any row that does not require an explicit address**,
read from the matrix (`requires_explicit_address`) rather than by naming rows,
so a row added later is covered without anyone remembering to. That is D03 and
D11, and it is checked over all 7 situations by 5 kinds.

---

## 4. Each binding constraint, and the test that discharges it

| Constraint | Discharged by | Test |
| --- | --- | --- |
| The prompt cannot be the only enforcement | runtime gate at three call sites; prompt kept and aligned through the turn context | `test_le_contrat_tient_meme_si_le_modele_n_a_jamais_lu_la_consigne`, `test_la_consigne_de_tour_ne_parle_de_presentation_que_en_presentation` |
| A visual command completes with **zero** `SpeechRequest`, observably as success | `_enqueue` gate, `PresentationSpeechGate.outcome()`, `voice.presentation.turn_silent` | `test_une_commande_visuelle_ne_fait_prononcer_aucune_parole`, `test_une_commande_visuelle_se_termine_sans_un_mot_et_cela_se_lit`, `test_un_tour_sans_aucune_demande_de_parole_est_une_reussite_distincte` |
| A genuine question speaks and displays | `KNOWLEDGE_QUESTION` admits `QUESTION` and `RESULT`; display never passes through the gate | `test_une_vraie_question_parle_pendant_la_meme_seance`, `test_une_vraie_question_parle_et_le_tour_n_est_pas_muet` |
| **D14, Simple must not regress**, all three voice architectures | gate inert outside PRESENTATION; no journal line; turn-context key absent at default | `test_le_mode_assistant_se_comporte_comme_avant_dans_les_trois_architectures` (6 cases, including a no-observer column), `test_le_mode_assistant_ne_laisse_aucune_trace_de_presentation` (3), `test_le_contexte_du_tour_ne_porte_le_mode_que_lorsqu_il_change_quelque_chose` |
| Ambient can never request speech | (a) `BrainTurnInput` refuses `AddressingDecision.AMBIENT`; (b) the gate refuses `AMBIENT_OBSERVATION` for all five kinds; (c) the Slice 06 import closure is untouched and re-run | `test_une_parole_ambiante_ne_peut_pas_naitre_faute_de_tour`, `test_une_situation_sans_adressage_explicite_ne_peut_jamais_obtenir_la_parole` (10 cases), `test_la_promotion_de_securite_n_ouvre_jamais_une_ligne_non_adressee`; `tests/unit/test_ambient_ingestion_lane.py` green |
| Errors and confirmations keep their safety semantics | `safety_speech_kinds` in the matrix; errors admitted even with no addressed turn (`UNADDRESSED_SAFETY_KINDS`) | `test_une_panne_n_est_jamais_tue_sur_un_tour_adresse` (5), `test_une_panne_et_une_clarification_restent_audibles_sur_une_commande_visuelle`, `test_un_relais_spontane_ne_parle_pas_mais_une_panne_spontanee_si` |
| Suppress filler, keep hearing repair and clarification | only `ReflexAction.PREAMBLE` is converted to `WAIT` with reason `presentation_no_filler`, in the runtime, never in `decide_reflex` | `test_le_remplissage_est_supprime_mais_la_politique_de_reflexe_survit`, `test_hors_presentation_le_preambule_repart_sur_le_meme_ordonnanceur`, `test_une_clarification_n_est_jamais_tue_sur_un_tour_adresse` (5) |
| Trace with non-content metadata only | the gate stores the situation, never the text | `test_aucune_trace_de_la_porte_ne_transporte_la_transcription`, plus an in-suite assertion that the spoken text never appears in the scheduler journal |
| Live mode, never stored | the gate re-reads `mode()` on every decision, through `InteractionModeObserver` | `test_un_changement_de_mode_en_cours_de_seance_est_pris_au_tour_suivant` |
| "X can never happen" is a test case | the four such sentences in the new modules are parametrised tests over the state the guard exists for, not over a convenient one | see the ambient, promotion, error and clarification rows above |
| Make invariants observable | `PresentationSpeechGate.outcome()` distinguishes `silent_by_policy` from `silent_no_speech` | `test_un_tour_sans_aucune_demande_de_parole_est_une_reussite_distincte` |
| No tests asserting on source text | none. One absence proof, and it reads **journal events**, not source | `test_le_mode_assistant_ne_laisse_aucune_trace_de_presentation` |

### Journal vocabulary added (metadata only)

| Kind | Level | When |
| --- | --- | --- |
| `voice.presentation.turn_classified` | info | a turn is classified |
| `voice.presentation.speech_withheld` | info | a speech is refused (renamed in rework) |
| `voice.presentation.classification_failed` | warning | the classifier raised; the turn fell back to **speech** |
| `voice.presentation.turn_silent` | info | a turn ended without a word |

`voice.presentation.turn_silent` is written when it is certain nothing more will
come for that turn: on the arrival of the next addressed turn, and on `stop()`.
It is deliberately **not** written on `brain.work.completed`, because
`ControlCenterBrainBackend._settle_success` publishes `COMPLETED` *before* the
turn's speech; settling there would date the balance from before the only thing
it counts. The read is immediate, only the journal line waits one turn.

---

## 5. Mutation testing: 47 attempts, 7 survivors, all closed

Run with a harness that patches production source, runs the suite, restores it,
and reports (scratchpad only, not committed). Every mutation below was applied
and reverted; the tree is byte-identical afterwards.

**Round 1, 24 mutations, 24 caught, 0 survivors.** M1 visual verb before speak
request; M2 promotion without the address guard; M3 `QUESTION` removed from the
safety kinds; M4 `ERROR` removed; M5 unaddressed speech always admitted; M6
never admitted; M7 gate always active; M8 never active; M9 `_enqueue` stops
consulting the gate; M10 preamble no longer filtered; M11 Duplex path ignores
the gate; M12 preamble always allowed; M13 silent balance never written; M14 a
new turn no longer settles the previous; M15 the trace carries the transcript;
M16 mode always joined to the turn context; M17 the brief paragraph always
appended; M18 Core stops handing the mode to the backend; M19 classifier
default becomes `VISUAL_COMMAND`; M20 an admitted speech is not counted; M21
question word matched anywhere; M22 turn memory unbounded; M23 any correlation
becomes a key; M24 an unreadable mode closes the gate.

**Round 2, 9 mutations, 3 caught, 2 survivors, 4 mis-encoded and re-run in
round 3.**

- **SURVIVOR M25**: the withheld-kinds bound (`MAX_WITHHELD_MEMORY`) removed
  and nothing failed. Closed by `test_la_liste_des_natures_retenues_est_bornee`.
- **SURVIVOR M37**: the wake-word strip removed from `normalized_tokens` and
  nothing failed, *including* `test_surface_reflex_policy.py` and
  `test_reflex_gate.py`. That is a **pre-existing gap in the reflex suite**: the
  wake-word strip in `conversational_wait_reason` had never been tested. Closed
  by `test_le_mot_d_eveil_ne_masque_pas_le_mot_interrogatif`, which asserts both
  the classifier's evidence and `conversational_wait_reason("Jarvis, ok")`.

**Round 3, 7 mutations, 5 caught, 2 survivors.**

- **SURVIVOR M28**: the scheduler's `try/except` around classification was
  unreachable, because nothing inside the gate could raise. Making it reachable
  exposed a **real design defect**, not just a test gap: with classification
  failed, no turn was recorded, so every speech of that turn fell to the "no
  addressed turn" rule and was silenced except `ERROR`. That directly
  contradicts this slice's own stated bias. **Fixed by moving the guard into the
  gate** behind an injectable `classify` seam: a failed classification now
  records the turn as `KNOWLEDGE_QUESTION` with evidence
  `classification_failed` and warns. The unreachable outer `try` was deleted
  rather than kept as decoration. Closed by
  `test_un_classement_en_panne_retombe_sur_la_parole_et_le_dit`.
- **SURVIVOR M40**: moving the gate *before* the dedup check changed nothing. A
  retransmitted `brain.speech.requested` would have been counted and traced
  twice, making the turn's balance and its journal line both wrong. Closed by
  `test_une_demande_de_parole_recue_deux_fois_n_est_retenue_qu_une_fois`.

**Round 4, 4 mutations, 4 caught**: M40 re-check plus three on the new
classification fallback (silent fallback, unlogged fallback, lost turn).

**Round 5, 3 wiring mutations, 2 caught, 1 survivor.**

- **SURVIVOR M49**: deleting `on_addressed_turn=speech.note_addressed_turn`
  from `voice_v2.py` broke nothing. The composition root was unverified, which
  is the Slice 05 lesson verbatim: a correct contract wired nowhere. Closed by
  `test_la_composition_de_production_cable_la_politique_sur_le_bridge`, which
  wakes the real `PersistentVoiceRuntime` and asserts that the live bridge holds
  the live scheduler's own method. Re-run: 3 of 3 caught.

**Round 1 re-run after every fix: 24 of 24 still caught.**

Guard probing (the "make it fail, then remove the probe" rule) was done through
this harness rather than by hand: every guard added by this slice was made to
fail at least once by a mutation that was then reverted.

---

## 6. Exact commands and counts

All foreground, narrow lists, `-p no:cacheprovider`, prefix
`.venv/Scripts/python.exe -m pytest`.

| Files | Result |
| --- | --- |
| `test_presentation_response_policy.py` | **91 passed** |
| `test_presentation_response_policy` + `test_v2_speech_scheduler` + `test_speech_presentation_scheduler` + `test_speech_presentation` + `test_reflex_gate` + `test_surface_reflex_policy` + `test_reflex_frontend_cleanup` + `test_v2_continuous_live` + `test_voice_duplex` + `test_voice_composition` | **409 passed** |
| `test_interaction_mode_contract` + `test_interaction_mode_control_plane` + `test_interaction_mode_protocol` + `test_interaction_mode_hud_js` + `test_ambient_ingestion_lane` + `test_presentation_working_set` + `test_presentation_audio_capture` | **565 passed** |
| `test_brain_card_state` + `test_brain_delegation` + `test_brain_interrupted_speech` + `test_brain_outcome_protocol` + `test_brain_outcome_review_races` + `test_brain_work_context` + `test_v2_brain_orchestrator` + `test_v2_brain_contracts` + `test_v2_brain_migration` | **193 passed, 1 failed** (baseline, see below) |
| `test_voice_composition` + `test_voice_duplex` + `test_realtime_audio_lifecycle` + `test_v2_continuous_live` + `test_v2_architecture` + `test_conversation_presentation` + `test_control_center_quality` + `test_prompt_registry` + `test_app` | **305 passed** |
| `test_thinking_turn_abandon` + `test_barge_in_while_thinking` + `test_barge_in_sustain` + `test_v2_barge_in` + `test_speech_scheduler_review_races` + `test_conversation_event_mouth_producers` + `test_conversation_event_voice_bridge` + `test_v2_latency_telemetry` + `test_front_brain_hints` + `test_front_brain_hint_review` + `test_front_brain_sidecar_review` | **243 passed** |
| `test_back_brain_delegation` + `test_back_brain_tasks` + `test_back_brain_worker` + `test_back_brain_speculative` + `test_voice_to_claude` + `test_voice_turn_admission` + `test_testlab_bundle` + `test_voice_admission_review` | **262 passed** |
| `test_conversation_events` + `test_conversation_event_producers` + `test_conversation_event_forwarder` + `test_conversation_event_trace` + `test_live_runtime_safety` + `test_live_lifecycle_protocol` + `test_live_idle_policy` + `test_live_idle_composition_review` + `test_environment` | **289 passed** |
| `test_owner_barge_in` + `test_owner_input_gate` + `test_owner_replay` + `test_solo_owner_acceptance` + `test_v2_voice_activity` + `test_v2_voice_toggle` + `test_device_playback_completion` + `test_v2_playback_cursor` + `test_conversation_transcript` | **231 passed** |
| `test_documented_routes` + `test_third_party_bootstrap` | **12 passed** |
| integration: `test_simple_front_brain_composition` + `test_voice_production_composition` + `test_back_brain_voice_composition` + `test_front_brain_composition_review` + `test_speech_presentation_race` + `test_speech_multichunk_composition` + `test_reflex_preamble_race` + `test_reflex_visual_alternation` + `test_background_failure_speaks` + `test_thinking_turn_abandon_protocol` + `test_duplex_orb_states` + `test_voice_replay_regressions` + `test_voice_replay_safety_regressions` + `test_brain_work_context_protocol` + `test_v2_brain_protocol` | **67 passed** |

**Blast radius measured, not guessed.** `grep -rl` over `tests/` for
`speech_scheduler|SpeechScheduler|realtime_audio|RealtimeConversationBridge|control_center_brain|build_agent_brief|reflex_policy|voice_v2|v2_app|JarvisCoreApplication`
returned 75 unit files and 40 integration files; every one relevant to the
changed behaviour was run above.

**The batches overlap deliberately** (several files are re-run in more than one
list), so they are reported per batch rather than summed into a misleading
total. Every batch is green except one test. That single failure is
`test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`,
the handoff's declared baseline entry for that file. Confirmed pre-existing by
`git stash`, run, identical failure, `git stash pop`. No new failure anywhere.
The declared order-dependent flake,
`test_back_brain_tasks.py::test_persistent_storage_read_failure_preserves_owner_and_bounds_stop[owned_read]`,
was run in its batch and **passed**. No Scene suite is touched by this slice.

No microphone was opened, no network call and no model call was made.

---

## 7. Where SLICE.md and the live repository disagreed, stated rather than silently resolved

1. **"Suppress acknowledgement/backchannel/filler reflexes except hearing
   repair/required clarification."** `ReflexAction` carries `BACKCHANNEL` and
   `DELEGATE`, but in this repository `decide_reflex` can only return `WAIT`,
   `SPEAK` or `PREAMBLE`. `BACKCHANNEL` and `DELEGATE` exist only as an
   *advisory* Front Brain hint (`suggested_action`) with **no production
   consumer**: grep finds the enum in `front_brain_hints.py` and in the JSON
   schema, nowhere else. And required clarification is not carried by the
   reflex channel at all: `REFLEX_INSTRUCTION` explicitly forbids the
   preamble to ask a question. So the suppression is scoped to `PREAMBLE`,
   and "clarification survives" is discharged on the **speech** channel,
   through `SpeechKind.QUESTION`. If the intent was to gate the advisory hint
   too, that is a no-op today and should be revisited when a consumer exists.

   **Corrected in rework:** round 1 also claimed hearing repair "arrives as
   `SpeechKind.QUESTION`". That is wrong. Hearing repair lives in
   `CONTINUOUS_BRAIN_OPERATING_RULES` (`jarvis/adapters/openai_realtime.py`),
   and in continuous mode the surface cannot speak unbidden at all —
   `CONTINUOUS_TURN_FLAGS` sets `create_response: False`. **Hearing repair has
   no production path today, in either interaction mode**, and this slice
   neither opens nor closes one. Required clarification is a different thing,
   and it does now have one.

2. **"Carry interaction mode/turn role into brain context/admission."** The
   mode is now in the brain **context**. It is deliberately **not** in
   `BrainTurnInput` nor in voice admission: `BrainTurnInput` is wire-encoded
   and persisted, the surface would become a second owner of a value Core owns,
   and D15 records that Core owns the effective mode. The "turn role" half is
   already covered by the existing `AddressingDecision` (`addressed` /
   `uncertain`, with `ambient` mechanically refused), which G7 says must not be
   widened, so nothing was added there.

3. **`VISUAL_COMMAND` and the `SpeechKind.QUESTION` hole.** SLICE.md and the
   matrix as written would have silenced a clarification question on a visual
   command turn, producing a turn with neither a screen change nor a sentence.
   Round 1 resolved it by layering a kind-driven re-situation on top of the
   matrix. **Agent 0 adopted the exception and rejected the form**: what the
   Human locked is the decision log, not Slice 01's generalisation of it, so
   the rework amended the matrix instead (section 9). Round 1 also protected
   a `SpeechKind.QUESTION` that **no production site emitted**; the rework
   gives it a producer.

4. **Duplex's `request_conversation` is not mentioned anywhere in SLICE.md.**
   It is a real speech path in one of the three architectures, so it is gated.
   The consequence is written into the doc: in Presentation plus Duplex, a
   direct spoken clarification on a visual-command turn is refused, because the
   direct path carries no `SpeechKind` to protect.

---

## 8. What I could not satisfy, and known limits

- **`HV-PRES-SPEECH-01` is not marked done**, as instructed, and it must now be
  run **once per voice architecture**, not once. B1 is precisely the failure a
  single-architecture human check would have missed: the policy was correct,
  tested, and completely inert on SIMPLE, FRONT_BRAIN and DUPLEX, while the
  `continuous_brain` path — the one a single check would most likely have
  exercised — behaved exactly as designed.
- **No runtime validation was performed.** Exercising this needs a live
  Realtime credential and the room microphone, which the instructions forbid
  and which the user's own Voice process holds.
- **A spontaneous relay inherits the last addressed turn's situation.**
  `BrainOrchestrator._relay_notice` reuses the *current* source's
  `correlation_id`, so a background sub-agent finishing right after a genuine
  question is judged under that question and may speak. After a
  `VISUAL_COMMAND` it is silent; with no current source it is judged
  unaddressed, so `ERROR` only. Narrowing this needs a provenance field the
  transport does not carry today. Written into the doc's "Known limits".
- **The classifier is lexical and French only**: three word lists, no model.
  `supprime` and `efface` are deliberately absent from the display verbs
  (ambiguous between a file and a scene object; muting a file-deletion
  confirmation would invert D09). A phrasing outside the lists falls to
  "answer", which is the safe direction, but it means an unrecognised display
  command still produces a spoken confirmation.
- **The `turn_silent` journal line lags by one turn**, see section 4. The read
  is immediate; only the written line waits for certainty.
- **Incidental find, not fixed:** the wake-word strip in
  `conversational_wait_reason` had no test at all before this slice (mutation
  M37). It now has one, inside this slice's suite rather than in
  `test_surface_reflex_policy.py` where it arguably belongs; moving it would
  have widened this diff into a file this slice otherwise does not touch.

---

## 9. Rework (second commit)

Two QA passes converged on two blocking findings. Their evidence is kept in
`qa/QA-REPORT.md`.

### B1 — the policy was inert on three of the four architectures

`realtime_audio.py` returns inside `if self.direct_conversation:` **before** the
line that classified the turn, and `voice_v2.py` sets `direct_conversation` from
`conversation_architecture`, which is one of SIMPLE / FRONT_BRAIN / DUPLEX. So
on every typed architecture the gate was never told a turn existed,
`request_conversation` judged every answer as "no addressed turn", and
PRESENTATION was **completely mute**. Only the legacy `continuous_brain` path
behaved as designed. This is readiness gap G1 — two voice-architecture axes
coexist — biting for real, and it inverted my own stated reason for gating
`request_conversation`.

The repair is not a moved line: `_last_correlation_id` is only assigned in
`_submit_brain_turn`, so it is `None` on that path and the classification would
have returned at its own guard. `_note_addressed_turn` now takes the
correlation explicitly, and the direct branch passes
`accepted.source.correlation_id` — the same identity `request_conversation`
reads — **before** proposing the response.

**The tests were the real defect.** `test_la_voie_directe_de_duplex_obeit_a_la_meme_politique`
primed the gate by calling `note_addressed_turn` itself, exercising the guard's
code without ever reaching the state the guard exists for, and its name asserted
the opposite of live behaviour. That is the Slice 06 pattern for the third time
in this task. Replaced by:

- `test_la_voie_directe_classe_le_tour_puis_obeit_a_la_politique` — five cases
  over mode × phrasing, driven only by `bridge._handle_transcript` on the real
  direct harness (`CoreBoundary` / `DirectSessionBoundary`), wired exactly as
  `voice_v2` wires it. Nothing is primed;
- `test_la_voie_directe_classe_le_tour_sous_l_identite_que_l_admission_rend` —
  asserts `_last_correlation_id is None` on that path, so the original bug
  cannot come back by attribute;
- `test_les_trois_architectures_typees_passent_par_la_voie_directe` — resolves
  each of the three typed configurations and asserts `direct_conversation`, so
  "the direct path is tested" is a statement about all three rather than about
  Duplex alone. `continuous_brain` is asserted to be the other path.

`test_la_composition_de_production_cable_la_politique_sur_le_bridge` now also
asserts which path it covers (`direct_conversation is False`) and names the two
tests that prove reachability, since an attribute being wired proves nothing
about the call site.

Mutations: R1 (direct branch stops classifying), R2 (**the original bug**, the
direct branch reads `_last_correlation_id`), R3 (classification moved after the
response is proposed) — all three caught. M47/M48 re-run for the brain path,
caught. M49 (composition stops wiring) caught.

### B2 — the deviation stands; the form does not. The matrix was amended.

Agent 0 adopted the exception and rejected its shape, for two reasons I accept:
my `COMMAND_ERROR` precedent is **outcome**-driven (the command ran and failed),
while my re-situation was **label**-driven (it keyed off a field); and
`SpeechKind.QUESTION` had **no production producer at all** — every production
site hard-codes `RESULT`, `ERROR`, `ACK` or the `PROGRESS` default — so the
clarification I justified the deviation with was still silenced on the only
reachable path, while my two tests for it passed against an implementation
where nothing could ever produce that kind.

**The exception is now data.** `PresentationOutputPolicy` carries
`safety_speech_kinds`, validated in `__post_init__` exactly like `speech_kinds`:
a safety kind still requires an explicit address (so no ambient or fact-check
row can carry one), it may not overlap `speech_kinds`, and it may not repeat.
`may_speak()` reads both columns and is the whole truth again;
`SAFETY_SITUATIONS` and `judged_situation` are **deleted**. The previously
undocumented `situation=None, kind=ERROR` rule — the sharper deviation, since it
grants speech with no address at all — is now `UNADDRESSED_SAFETY_KINDS` in the
domain, with its argument written next to it, and it is in the doc's table.

**The producer.** Of the two options offered I took the first — give
clarifications a real producer — because the second is not reachable from this
slice: deciding "the turn produced no display action" needs a signal that
`/api/agent/ask` does not carry (its response is `{ok, text}`), so it would be a
cross-process contract change.

`public_answer_kind()` (`control_center_brain`) labels a public answer
`QUESTION` when it is **one interrogative sentence and nothing else**. Three
things make it a repair rather than a label:

- it is computed **by Core, from the content**. The agent writes French; it does
  not fill in a category, and a statement cannot declare itself a question
  without ceasing to be a statement;
- the bound is deliberately strict, so « Voilà le bilan. Tu veux aussi le Q4 ? »
  stays a `RESULT` and stays withheld — otherwise the kind would become an exit
  it suffices to punctuate;
- `SpeechKind.QUESTION` has had full semantics in Core since the beginning
  (`_revise_question` makes it an open point of the working state instead of an
  acquired public fact, and it is not retained as a durable outcome) and
  **nothing ever emitted it**, while the system prompt has always told the agent
  to settle an ambiguous request « en une question courte ». The lane was dead.

`_SENTENCE_END` requires the terminator to be followed by whitespace or the end
of the text, so « du 30.06 » does not split a real question into two sentences.

**D14.** The change applies in both modes, because nothing about it was ever
specific to Presentation. What the user hears is identical — same sentence, same
priority; only Core's bookkeeping becomes what the kind always meant. Measured:
the brain, orchestrator, contracts, work-context, outcome, migration,
card-state, protocol, control-centre and prompt suites are green, **zero test
touched**.

**And a written constraint on the boundary**, which is what keeps the exception
from becoming an exit later:
`test_aucun_site_de_production_ne_laisse_le_modele_nommer_sa_nature_de_parole`
enumerates every production `SpeechRequest(` site by AST against a declared
table and checks that each `kind=` value position is a literal `SpeechKind`
member or a call to a declared Core decider. It is a source-text assertion
proving an **absence**, the sanctioned exception (Slice 05 precedent), and its
docstring says so. **Probed**: a module doing `kind=SpeechKind(payload["kind"])`
dropped into `jarvis/runtime/` failed it by name; probe removed.

Mutations R4–R9, R14, R15 — all caught.

### B3 — the canonical page said the opposite of the behaviour

`docs/interaction-mode.md` is corrected where its meaning changed, not with a
cross-reference: the matrix table gains a **Safety kinds** column, the
`visual_command` row explains the two exceptions and why they are the outcome
rather than a label, the invariants list gains the two new construction-time
checks, and a new paragraph states that the kind is set by Core and names the
test that keeps it that way. `docs/presentation-response-policy.md` is updated
throughout.

The prompt no longer promises what the runtime refuses.
`BRIEF_PRESENTATION_MODE` now says clarification passes **if and only if** the
answer is a single interrogative sentence, with an example, and that a sentence
which answers and then asks counts as an answer. That is exactly
`public_answer_kind`'s rule, in the model's words.

### The rest

| # | Finding | What was done |
| --- | --- | --- |
| 1 | a `?` anywhere beat a display verb, so « Tu peux montrer le bilan ? » spoke | the question mark now comes **after** the display verb; a question word **at the head** still wins first, so « pourquoi tu as affiché le Q3 ? » stays a question. Both halves are tested (4 + 2 cases); mutations R10 and R11 caught |
| 2 | negation-blind: « montre le bilan, ne commente pas » spoke **because** the user refused | speak markers are matched on tokens with three tokens of lookback against `NEGATORS`; mutations R12 and R13 caught. The residual (other inflections, other clauses) is documented — a missed marker makes Jarvis speak, which is the safe side |
| 3 | back-brain delegation **failures** were `SpeechKind.ACK`, so a real failure went silent | the refusal is now `ERROR`, the acceptance stays `ACK`. This also makes the refusal durable rather than expiring after 45 s. One existing test asserted the old transient behaviour and now asserts both branches by name; mutation R16 caught |
| 4 | the M40 fix landed on one of two paths: `request_conversation` consumed the identity *after* the gate, so a refused answer was never deduplicated | `self._seen_speech_ids.add(identity)` moved before the gate, as in `_enqueue`; `test_une_reponse_directe_refusee_n_est_comptee_qu_une_fois` covers a repeated request; mutation R17 caught |
| 5 | "the gate holds no policy" was not literally true | corrected in §2 above, in the module docstring and in the doc: two rules are the gate's own and are named |
| 6 | the doc was wrong about the hearing-repair mechanism | corrected: hearing repair has no production path at all, in either mode |
| 7 | dead code | deleted: `observe_interaction_mode`'s `source` kwarg (never passed, never read — the listener contract is one positional argument), `SpeechScheduler.presentation_turn_outcome()` (no production caller), and the `try/except` in `PresentationSpeechGate.active` (an attribute read cannot raise — the same imaginary-guard shape I had already deleted around the classifier, so keeping it was inconsistent). The `classify` seam is kept: it backs a reachable fallback |
| 8 | `voice.speech.presentation_withheld` collided in meaning with the pre-existing `voice.speech.presentation_decided`, where "presentation" means delivery | renamed `voice.presentation.speech_withheld`, matching its three siblings. The mode-read warning it also carried is gone with item 7 |
| 9 | known limits | added to the doc: the two-views-of-the-mode race (prompt half reads Core's service, gate reads the Voice observer; one turn of possible disagreement, and neither direction loses speech), the residual classifier misses, and that `silent_no_speech` is not observable within its own turn |

### Rework mutations — 41, zero survivors

R1–R3 (direct-path wiring, including the original bug as a mutation) · R4–R9
(matrix: `may_speak` ignoring safety kinds, the two new construction invariants,
`VISUAL_COMMAND` losing its exceptions, the unaddressed rule in both directions)
· R10–R13 (classifier order in both directions, negation removed, negation
window zeroed) · R14–R15 (the producer too loose, the producer removed) · R16
(delegation refusal back to `ACK`) · R17 (direct path stops consuming the
identity before the gate) · R18 (the gate built without the observer) · M47/M48
(brain-path wiring) · M49 (composition wiring) · and the still-applicable 22 of
the first round, re-run against the reworked tree: M7–M29, M33, M44.

**All caught. No survivor in this round.**

Method note, because it cost an hour and would cost the next agent the same:
the scratchpad is **shared between agents**, and a QA agent had left harnesses
named `mutate.py` / `mutate5.py`. Running what I thought were my own scripts ran
theirs, which restored `presentation_speech_gate.py` and `speech_scheduler.py`
to `HEAD` mid-rework. The symptom was mutations reported as "caught" while the
suite was failing for an unrelated reason. Caught by `git diff --stat` showing
two expected files missing, edits re-applied, and **every mutation round re-run
from scratch** under `s7rework_*` names. All counts above are from the re-run.

### Tests re-run after the rework

Foreground, narrow lists, `-p no:cacheprovider`, on the restored tree.

| Files | Result |
| --- | --- |
| `test_presentation_response_policy` (119 tests, up from 91) + `test_interaction_mode_contract` + `test_interaction_mode_control_plane` + `test_interaction_mode_protocol` + `test_ambient_ingestion_lane` + `test_presentation_working_set` + `test_presentation_audio_capture` | **642 passed** |
| `test_v2_speech_scheduler` + `test_speech_presentation_scheduler` + `test_speech_presentation` + `test_reflex_gate` + `test_surface_reflex_policy` + `test_reflex_frontend_cleanup` + `test_v2_continuous_live` + `test_voice_duplex` + `test_voice_composition` + `test_realtime_audio_lifecycle` + `test_v2_architecture` + `test_conversation_presentation` | **341 passed** |
| the brain set + `test_core_brain_outcomes` + `test_back_brain_delegation` + `test_back_brain_worker` | **265 passed, 1 failed** (declared baseline) |
| `test_control_center_quality` + `test_prompt_registry` + `test_app` + `test_voice_to_claude` + `test_voice_turn_admission` + `test_back_brain_tasks` + `test_back_brain_speculative` + `test_voice_admission_review` | **261 passed** |
| `test_thinking_turn_abandon` + the barge-in set + `test_speech_scheduler_review_races` + the conversation-event set + `test_v2_latency_telemetry` + the front-brain set + `test_testlab_bundle` + `test_documented_routes` + `test_owner_barge_in` + `test_v2_voice_toggle` | **371 passed** |
| the 15 integration suites of §6 | **67 passed** |

The single failure is the declared baseline
`test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`.
The declared `[owned_read]` flake ran and passed.

**One new flake observed, and not dismissed.**
`test_back_brain_worker.py::test_cancel_during_spawn_retains_owner_then_closes_exact_process[claude]`
failed once inside a 90-second batch. Investigated rather than waved off: it
passes alone, it passes on a re-run of the **identical** command with identical
code, the same batch is green on the pre-rework tree *and* on the reworked one,
and the failing assertion is `await asyncio.wait_for(running, 2)` — a two-second
deadline on a spawn/cancel race, under a loaded machine. This slice touches no
back-brain worker code. It is a timing flake of the same family as the declared
`[owned_read]` one, and it belongs on the baseline list.

No microphone was opened, no network call and no model call was made.
