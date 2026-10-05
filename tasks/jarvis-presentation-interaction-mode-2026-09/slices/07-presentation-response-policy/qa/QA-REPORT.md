# QA — Slice 07, Presentation response policy

Branch `task/jarvis-presentation-interaction-mode`, commit `708eaef`.
Baseline QA pass (`qa-verification` + `debug`). No product code modified; tree
verified clean (`git status --porcelain` empty) after every experiment.

QA does not decide approve/rework. Findings are ordered most serious first.

---

## F1 — BLOCKING. In PRESENTATION, every `VoiceArchitectureId` stack (SIMPLE, FRONT_BRAIN, DUPLEX) goes completely mute

`jarvis/runtime/realtime_audio.py:4496-4522` — the addressed-transcript handler
returns inside the `if self.direct_conversation:` branch, **before**
`jarvis/runtime/realtime_audio.py:4550` where `_note_addressed_turn(text)` is
called. So on any direct-conversation stack the gate is never told a turn
exists.

`jarvis/runtime/voice_v2.py:651` sets
`direct_conversation=self.conversation_architecture is not None`, and
`conversation_architecture` is one of `SIMPLE` / `FRONT_BRAIN` / `DUPLEX`
(`jarvis/runtime/voice_v2.py:130`). The scheduler — with its gate — is built for
all of them (`jarvis/runtime/voice_v2.py:572-587`; `continuous` is true whenever
`conversation_architecture is not None`, `jarvis/runtime/voice_v2.py:230`).

Consequence: `SpeechScheduler.request_conversation`
(`jarvis/runtime/speech_scheduler.py:1722`) always calls
`presentation.admit(correlation_id=…, kind=SpeechKind.RESULT)` with an unknown
correlation, `admit_presentation_speech` takes the `situation is None` branch
(`jarvis/domain/presentation_response.py:205-212`) and refuses everything but
`ERROR` — and nothing on the direct path ever emits `ERROR`. Only
`continuous_brain` (`conversation_architecture=None`) reaches the classifier.

Reproduced on the live objects, not by reading. Harness built exactly as
`voice_v2` wires it (`on_addressed_turn=scheduler.note_addressed_turn`), on the
repository's own `direct_harness` boundaries
(`tests/integration/test_front_brain_composition_review.py:180`):

```
MODE=assistant    'Jarvis, quel est le total du trimestre ?'  requests=1
MODE=presentation 'Jarvis, quel est le total du trimestre ?'  requests=0
MODE=assistant    'Jarvis, dis-moi le total du trimestre'     requests=1
MODE=presentation 'Jarvis, dis-moi le total du trimestre'     requests=0
MODE=assistant    'Jarvis, montre-moi le bilan'               requests=1
MODE=presentation 'Jarvis, montre-moi le bilan'               requests=0
```

This breaks the Slice's own acceptance criterion "genuine question can
speak/display", and the `EXPLICIT_SPEAK_REQUEST` row of the locked matrix, in
three of the four production stacks.

**Why no test caught it (the Slice 06 pattern).**
`tests/unit/test_presentation_response_policy.py:584`
`test_la_voie_directe_de_duplex_obeit_a_la_meme_politique` primes the gate by
hand with `scheduler.note_addressed_turn(...)` before calling
`request_conversation`. It exercises the guard's code without ever reaching the
state the guard exists for, because production never puts the gate in that
state on this path. Its name asserts the opposite of the live behaviour.

`test_la_composition_de_production_cable_la_politique_sur_le_bridge`
(line 821) asserts `bridge.on_addressed_turn == speech.note_addressed_turn`,
which is also true on a Duplex composition — the attribute is wired, the call
site is unreachable. `test_le_bridge_remet_chaque_tour_adresse_a_la_politique`
(line 799) uses `build_bridge(...)`, whose `direct_conversation` defaults to
`False`.

---

## F2 — BLOCKING (the judgement call on the locked artifact). The `SpeechKind.QUESTION` promotion protects a path with no production producer, while the reachable clarification path is still silenced

The implementer's fix for the `VISUAL_COMMAND` hole re-situates
`SpeechKind.QUESTION → KNOWLEDGE_QUESTION`
(`jarvis/domain/presentation_response.py:113`, `:174-196`).

**`SpeechKind.QUESTION` has no production producer.** Every production
`SpeechRequest` construction site hard-codes the kind:

| Site | Kind |
| --- | --- |
| `jarvis/adapters/control_center_brain.py:387` (`_settle_success`) | `RESULT` |
| `jarvis/adapters/control_center_brain.py:417` (`_settle_failure`) | `ERROR` |
| `jarvis/core/brain_service.py:355`, `:810` | `RESULT` |
| `jarvis/core/brain_service.py:1498` | `ERROR` |
| `jarvis/runtime/back_brain_delegation.py:69` | `ACK` |
| `jarvis/adapters/openai_realtime_frontend.py:495` | default `PROGRESS` |

Only `jarvis/testlab/virtual/harness.py:602` and test files ever pass
`SpeechKind.QUESTION`.

Meanwhile the brain **is** instructed to ask a clarifying question
(`jarvis/runtime/claude_local.py:68`: « Quand sa demande peut se lire de deux
façons, tranche avec lui tout de suite, en une question courte »), and that
question returns through `_settle_success` as `SpeechKind.RESULT`. Verified
live:

```
turn   "Jarvis, montre-moi le bilan"                       -> visual_command
speech RESULT "De quel bilan parles-tu, le Q3 ou le Q4 ?"  -> spoken = []
outcome {silent: True, silent_reason: 'silent_by_policy', withheld: ['result']}
```

So the exact defect the judgement call was justified by — « un tour où JARVIS
n'a pas compris quel bilan montrer et qui ne peut pas le demander meurt en
silence » — still happens on the only reachable path. The promotion closes a
door nothing walks through.

Aggravating: `BRIEF_PRESENTATION_MODE`
(`jarvis/runtime/control_center.py:446-456`) tells the model « ce que tu n'as
pas compris se demande toujours » and « hors de ces cas, le runtime ne
délivrera pas ta phrase ». The runtime does drop exactly that phrase. The
aligned prompt and the runtime contradict each other.

Correspondingly vacuous tests:
`test_une_clarification_n_est_jamais_tue_sur_un_tour_adresse` (line 186) and the
`[SpeechKind.QUESTION]` case of
`test_une_panne_et_une_clarification_restent_audibles_sur_une_commande_visuelle`
(line 512). Both pass against an implementation where nothing can ever produce
that kind.

**On "could the brain exploit `QUESTION` to speak on every visual command?"** —
Not today, and not because the design prevents it: the brain cannot choose a
`SpeechKind` at all; the backend decides (`RESULT`/`ERROR`). If a later slice
lets the agent name its own kind, the exploit becomes trivial and the filler the
user rejected returns. This deserves a written constraint on the boundary.

---

## F3 — NON-BLOCKING but material (the classifier). A question mark anywhere beats a display verb, so a politely phrased visual command speaks

`jarvis/domain/presentation_response.py:158` tests `"?" in raw` **before** the
display-verb scan. Reading order is speak-request → `"?"` → question opener →
display verb → answer. Attack results:

| Transcript | Situation |
| --- | --- |
| `Tu peux montrer le bilan ?` | `knowledge_question` (`question_mark`) |
| `Montre-moi le bilan ?` | `knowledge_question` |
| `Jarvis, tu peux afficher le graphique ?` | `knowledge_question` |
| `Affiche le bilan, d'accord ?` | `knowledge_question` |
| `est ce que tu peux afficher le bilan` | `knowledge_question` (`question_opener:est_ce_que`) |

End-to-end: turn `"Jarvis, tu peux afficher le bilan ?"` → the brain's `RESULT`
**is spoken**, outcome `{situation: knowledge_question, admitted: 1}`. Realtime
ASR routinely punctuates interrogative intonation, and "tu peux afficher X ?" is
ordinary French for a display command. The failure direction is *towards speech*,
so it is safe on the silent-failure axis, but it re-creates the filler D09 exists
to remove. Stated in neither `REPORT.md` §8 nor the doc's "Known limits".

### Other classifier attacks (all non-blocking)

| Transcript | Situation | Direction |
| --- | --- | --- |
| `jarvis show me the balance sheet` | `knowledge_question` (`no_visual_command_evidence`) | safe; documented FR-only limit |
| `jarvis open the dashboard` | `knowledge_question` | safe |
| `affiche le dashboard please` | `visual_command` | correct |
| `ouvre la note intitulee "dis moi tout"` | `explicit_speak_request` | quoted-string leak; speaks on a pure display command |
| `cree une note qui dit "montre moi le bilan"` | `visual_command` | quoted-string leak; **silences** a non-display turn |
| `supprime le fichier compta`, `efface la note` | `knowledge_question` | safe, as documented |
| `on a vendu combien ce trimestre` (no `?`) | `knowledge_question` | safe |
| `le bilan il est ou` | `knowledge_question` | safe |
| `affiche le graphique ou le tableau` | `visual_command` | correct — the head-only opener rule works |
| `""`, `"   "`, `"jarvis"`, `"ok"` | `knowledge_question` | safe |
| `commente ce graphique` | `explicit_speak_request` | correct |
| `montre-moi le bilan et dis-moi le total` | `explicit_speak_request` (`speak_request:dis_moi`) | correct, as claimed |

Unpunctuated ASR and mid-phrase question words behave as designed; the only
lexical misses fall on the speak side except the two quoted-string cases.

---

## F4 — NON-BLOCKING. Back-brain delegation failures are `SpeechKind.ACK` and are now silenced

`jarvis/runtime/back_brain_delegation.py:62-69` sends « Je ne peux pas lancer ce
travail en arrière-plan pour le moment. » with `kind=SpeechKind.ACK`. On a
`VISUAL_COMMAND` or `KNOWLEDGE_QUESTION` turn the gate refuses `ACK`, so a real
delegation failure is silent. The mis-kinding is pre-existing; this slice makes
it consequential. Suppressing the success variant ("Je m'en occupe.") is
correct and desirable.

---

## F5 — OBSERVATION (filler suppression). Both report claims verified, but the surviving channels are empty

- **`BACKCHANNEL`/`DELEGATE` have no production consumer — CONFIRMED.**
  `decide_reflex` (`jarvis/domain/reflex_policy.py:62-95`) can only return
  `WAIT`, `SPEAK` or `PREAMBLE`. `suggested_action` is read once at
  `jarvis/runtime/front_brain_hints.py:139` to pick an *ignore reason*; the
  `HintConsumption` returned by `consume(...)` is discarded by its only caller
  (`jarvis/runtime/front_brain_sidecar.py:306`).
- **Clarification does not travel on the reflex channel — CONFIRMED.**
  `REFLEX_INSTRUCTION` (`jarvis/adapters/openai_realtime.py:170`) explicitly
  forbids « poser une question ».
- **But hearing repair has no production path either.**
  `SURFACE_HEARING_REPAIRS` and the clarification allowance live in
  `CONTINUOUS_BRAIN_OPERATING_RULES` (`jarvis/adapters/openai_realtime.py:61`,
  `:82-86`), and in continuous mode the surface cannot speak unbidden:
  `CONTINUOUS_TURN_FLAGS = {"create_response": False, …}`
  (`jarvis/adapters/openai_realtime.py:151`, applied at `:252`). The doc
  sentence "Hearing repair and required clarification … arrive as
  `SpeechKind.QUESTION`" (`docs/presentation-response-policy.md:166`) is
  therefore wrong about the mechanism and vacuous about the outcome. See F2.

---

## F6 — OBSERVATION (`turn_silent` lag). Not misleading, but one case is unobservable within the turn

`_settle_success` does publish `COMPLETED` before the speech
(`jarvis/adapters/control_center_brain.py:366-393`), so the decision not to
settle there is right. `settle_all` runs on the next addressed turn
(`jarvis/runtime/presentation_speech_gate.py:160`) and in `stop()`
(`jarvis/runtime/speech_scheduler.py:422`) — both verified.

Within a turn: `silent_by_policy` is observable immediately, because every
refusal writes `voice.speech.presentation_withheld`. `silent_no_speech` is not —
only `voice.presentation.turn_classified` exists until the next turn, so that
one case is distinguishable from a dead turn only by cross-reading
`brain.work.completed` / `brain.work.failed` on another channel.
`presentation_turn_outcome()` is immediate but is a Python API, not a journal
line.

Minor: when the mode is switched away from PRESENTATION mid-session,
`note_addressed_turn` returns before `settle_all`
(`presentation_speech_gate.py:135`), so pending turns wait for `stop()`.
Bounded and harmless.

---

## Verified as claimed

- **D14 — the gate is inert outside PRESENTATION.** `admit` returns
  `(True, None, None, "mode_not_presentation")` before touching memory or
  journal (`presentation_speech_gate.py:186-189`); `note_addressed_turn` and
  `allows_preamble` gate on the same `active` property. The absence is tested
  on observed events, not source
  (`test_le_mode_assistant_ne_laisse_aucune_trace_de_presentation`). The only
  journal line ever written outside PRESENTATION is the
  `presentation_gate_mode_unreadable` warning when `mode()` raises, which the
  lambda the scheduler installs cannot do (`speech_scheduler.py:253-258`).
  Simple, Front Brain and Duplex composition suites all green (see table).
- **D11 holds under the re-situation mechanism.** Exhaustive 7 situations × 5
  kinds: `AMBIENT_OBSERVATION` and `FACT_CHECK_ATTENTION` refuse all five,
  `judged_situation` returns them unchanged, zero violations. The condition is
  read from `requires_explicit_address`, so a row added later is covered. No
  promotion path found. `classify_addressed_situation` never returns
  `AMBIENT_OBSERVATION`, and `_note_addressed_turn` is reached only after
  `decision is AddressingDecision.ADDRESSED` and a successful brain submit
  (`realtime_audio.py:4460`, `:4526-4550`).
- **Ambient import closure unchanged.** `jarvis.runtime.ambient_lane` loads
  exactly the 20 declared modules, re-measured in a fresh interpreter. The two
  new modules are domain-clean (`presentation_response` pulls
  `output_disposition`, `presentation_policy`, `reflex_policy`,
  `speech_presentation`, `v2`; the gate adds `interaction_mode` only).
  `tests/unit/test_ambient_ingestion_lane.py` green.
- **`reflex_policy` extraction is behaviour-preserving.** The diff is a pure
  lift of the normalisation block; `conversational_wait_reason`'s body is
  unchanged.
- **Errors stay audible.** `SpeechKind.ERROR` on a `VISUAL_COMMAND` turn is
  spoken end-to-end through the scheduler. Verified live.
- **Zero `SpeechRequest` on a visual command.** `spoken == []`,
  `_pop_next() is None`, outcome `silent_by_policy`, `withheld == ['result']`.
- **Trace hygiene.** Planted `ZZQAPLANTEDPHRASE1234` into both the transcript
  and the speech text; it appears in **zero** gate events
  (`turn_classified`, `presentation_withheld`, `turn_silent`,
  `classification_failed`). Its one appearance is the pre-existing
  `voice.speech.abandoned` scheduler event. `_fields()`
  (`speech_scheduler.py:2089`) carries no text. The slice does not copy the
  `text[:300]` pattern of `voice.transcript_dropped` (`Issues/002`);
  `realtime_audio.py:4472` and `:2427` still do, both pre-existing and out of
  scope.

---

## Mutation re-run

12 mutations applied to production source, suite run, source restored; the tree
was byte-identical and `git status` clean afterwards.

| Id | Mutation | Result |
| --- | --- | --- |
| M28 | failed classification loses the turn again (pre-fix behaviour) | CAUGHT |
| M49 | `voice_v2` stops wiring `on_addressed_turn` | CAUGHT |
| M9 | `_enqueue` stops consulting the gate | CAUGHT |
| M2 | promotion without the `requires_explicit_address` guard | CAUGHT |
| M21 | question word matched anywhere, not only at the head | CAUGHT |
| M25 | `MAX_WITHHELD_MEMORY` bound removed | CAUGHT |
| M11 | Duplex direct path ignores the gate | CAUGHT |
| M10 | preamble no longer filtered in Presentation | CAUGHT |
| M13 | silent balance never written | CAUGHT |
| QA-M1 | the **bridge** stops calling `_note_addressed_turn` | CAUGHT |
| QA-M2 | `situation=None` admits every kind | CAUGHT |
| QA-M3 | the matrix ceiling bypassed for every addressed row | CAUGHT |

M28 and M49 both confirmed closed. The mutation suite is genuinely strong on
the code paths it covers; F1 shows it does not cover the direct-conversation
*reachability*, because the only test of that path primes the state by hand.

---

## Tests re-run by QA

All foreground, narrow lists, `-p no:cacheprovider`.

| Files | Result |
| --- | --- |
| `test_presentation_response_policy` | 91 passed |
| `test_v2_speech_scheduler` + `test_speech_presentation_scheduler` + `test_speech_presentation` + `test_reflex_gate` + `test_surface_reflex_policy` | 144 passed |
| `test_interaction_mode_contract` + `test_interaction_mode_control_plane` + `test_ambient_ingestion_lane` + `test_voice_composition` + `test_v2_voice_toggle` | 341 passed |
| `test_brain_delegation` + `test_v2_brain_orchestrator` + `test_v2_brain_contracts` + `test_brain_work_context` + `test_brain_outcome_protocol` | 145 passed, **1 failed (declared baseline)** |
| integration: `test_simple_front_brain_composition` + `test_voice_production_composition` + `test_back_brain_voice_composition` + `test_front_brain_composition_review` + `test_speech_presentation_race` + `test_reflex_preamble_race` + `test_reflex_visual_alternation` + `test_background_failure_speaks` | 32 passed |
| `test_v2_continuous_live` + `test_voice_duplex` + `test_realtime_audio_lifecycle` + `test_v2_architecture` + `test_conversation_presentation` + `test_prompt_registry` + `test_control_center_quality` + `test_app` | 298 passed |
| `test_interaction_mode_protocol` + `test_presentation_working_set` + `test_presentation_audio_capture` + `test_back_brain_delegation` + `test_back_brain_tasks` + `test_voice_turn_admission` + `test_voice_to_claude` | 363 passed |
| `test_conversation_event_producers` + `test_conversation_event_voice_bridge` + `test_conversation_event_mouth_producers` + `test_speech_scheduler_review_races` + `test_v2_barge_in` + `test_front_brain_hints` + `test_front_brain_sidecar_review` + `test_reflex_frontend_cleanup` | 151 passed |

The single failure is
`test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`,
the declared baseline entry for that file. The declared order-dependent flake
`test_back_brain_tasks.py::…[owned_read]` passed. No new failure anywhere.

---

## Not verified

- **No runtime validation.** No microphone, no network, no model call. The live
  Voice stack, the real Realtime provider and the Control Center UI were not
  exercised. `HV-PRES-SPEECH-01` remains open — and F1 means the human check
  must be run **per voice architecture**, not once.
- The 24 declared Scene-suite baseline failures were not re-run; the slice
  touches no Scene code.
- Prompt / agent-trace analysis (`agent-trace-analysis`) was not performed; no
  agent run artifacts were inspected.
- `InteractionMode.REUNION` is reserved and was not exercised.
